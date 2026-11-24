"""定期巡查：到时间自动生成任务。

由定时任务每分钟调用 run_due()：
- 找出 next_run_at 已到的巡查项
- 服务器停机期间错过多次时，只给最近一次派任务，较早的记为 skipped（不会一下子冒出一堆）
- 每次派发写 inspection_runs，(巡查项, 触发时间) 唯一，重启或重复执行不会重复派
- 内容翻译：同样的内容之前派发过且已翻译，就直接复用译文
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit, translation_service
from .config import get_settings
from .db import SessionLocal
from .inspection_schedule import Rule, assignment, next_occurrence
from .models import InspectionRun, InspectionTemplate, Task, Worker, utcnow
from .schedule_service import load_schedule
from .translator import LANGS

log = logging.getLogger("inspection")
MAX_CATCHUP = 500


def to_local(d: datetime) -> datetime:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(get_settings().tz).replace(tzinfo=None)


def to_utc(local: datetime) -> datetime:
    return local.replace(tzinfo=get_settings().tz).astimezone(timezone.utc)


def rule_of(t: InspectionTemplate) -> Rule:
    return Rule(kind=t.kind, at_time=t.at_time, every_n=t.every_n, weekdays=list(t.weekdays or []),
                month_days=list(t.month_days or []), year_dates=list(t.year_dates or []), shift_kinds=list(t.shift_kinds or []),
                start_date=t.start_date, assign=t.assign, team_id=t.team_id)


def schedule_next(db: Session, t: InspectionTemplate, after_local: datetime | None = None) -> None:
    """重新计算下一次触发时间（严格晚于 after_local，默认现在）。"""
    if not t.enabled:
        t.next_run_at = None
        return
    after_local = after_local or to_local(utcnow())
    nxt = next_occurrence(rule_of(t), after_local, load_schedule(db))
    t.next_run_at = to_utc(nxt) if nxt else None


def _copy_translation(db: Session, t: InspectionTemplate, task: Task) -> bool:
    """之前同样内容的巡查任务已翻译好 → 复制译文，不用再翻译。"""
    prev = db.scalar(select(Task).where(Task.inspection_id == t.id, Task.translation_status == "done")
                     .order_by(Task.id.desc()).limit(1))
    if prev is None or t.content.strip() not in {prev.content_zh, prev.content_sr, prev.content_en}:
        return False
    for l in LANGS:
        setattr(task, f"content_{l}", getattr(prev, f"content_{l}"))
    task.source_lang = prev.source_lang
    task.translation_status = "done"
    return True


def create_task(db: Session, t: InspectionTemplate, occ_local: datetime, run_status: str = "created",
                user_id: int | None = None) -> InspectionRun:
    """为一次触发生成任务并记录。调用方负责 commit；返回本次记录（status=failed 时没有任务）。"""
    sched = load_schedule(db)
    team, shift_date, shift_kind = assignment(rule_of(t), occ_local, sched)
    occ_utc = to_utc(occ_local)
    run = InspectionRun(template_id=t.id, occurrence_at=occ_utc, status=run_status,
                        team_id=team.id if team else None, created_at=utcnow())
    if team is None:
        run.status, run.note = "failed", "no team on duty / team not found"
        db.add(run)
        return run
    if t.sub_items:  # 有小项目：生成一个项目，每个小项目一个子项目
        _create_project(db, t, run, team, (shift_date, shift_kind), occ_utc, occ_local, user_id)
        return run
    now = utcnow()
    task = Task(
        client_id=str(uuid.uuid4()), source_lang=t.lang, team_id=team.id, origin_team_id=team.id,
        inspection_id=t.id, status="not_started", shift_date=shift_date, shift_kind=shift_kind,
        created_by=user_id or t.updated_by, updated_by=user_id or t.updated_by,
        recorded_at=occ_utc, created_at=now, updated_at=now, chain_started_at=occ_utc, handover_count=0,
        translation_status="pending", manual_fields=[],
    )
    if not _copy_translation(db, t, task):
        setattr(task, f"content_{t.lang}", t.content.strip())
    if t.assign == "fixed" and t.worker_ids:
        task.workers = list(db.scalars(select(Worker).where(Worker.id.in_(t.worker_ids), Worker.is_active.is_(True))))
    db.add(task)
    db.flush()
    run.task_id = task.id
    db.add(run)
    audit.log(db, user_id=user_id, action="auto_create" if user_id is None else "create", entity="task",
              entity_id=task.id, new={"inspection_id": t.id, "inspection": t.name, "occurrence": occ_local.isoformat(),
                                       "team_id": team.id, "shift": f"{shift_date} {shift_kind}"})
    return run


def _create_project(db: Session, t: InspectionTemplate, run: InspectionRun, team, slot, occ_utc, occ_local,
                    user_id: int | None) -> None:
    """有小项目的巡查：生成项目（名称 = 巡查项名称）+ 子项目。上一次的译文一样就直接复制，不用再翻译。"""
    from . import project_service
    from .models import Project

    actor = user_id or t.updated_by
    now = utcnow()
    prev = db.scalar(select(Project).where(Project.inspection_id == t.id).order_by(Project.id.desc()).limit(1))
    p = Project(source_lang=t.lang, translation_status="pending", transferable=t.transferable, team_id=team.id,
                inspection_id=t.id, created_by=actor, updated_by=actor, created_at=now, updated_at=now)
    if prev is not None and prev.translation_status == "done" and t.name.strip() in {prev.name_zh, prev.name_sr, prev.name_en}:
        p.name_zh, p.name_sr, p.name_en, p.source_lang, p.translation_status = (
            prev.name_zh, prev.name_sr, prev.name_en, prev.source_lang, "done")
    else:
        setattr(p, f"name_{t.lang}", t.name.strip())
    db.add(p)
    db.flush()
    # 上一次生成的子项目里已经翻译好的：按内容复制译文
    done_before = {}
    if prev is not None:
        for old in db.scalars(select(Task).where(Task.project_id == prev.id, Task.translation_status == "done")):
            for l in LANGS:
                if getattr(old, f"content_{l}"):
                    done_before.setdefault(getattr(old, f"content_{l}"), old)
    for item in t.sub_items:
        worker = db.get(Worker, item["worker_id"]) if item.get("worker_id") else None
        if worker is not None and not worker.is_active:
            worker = None
        team_id = item.get("team_id") or team.id
        sub = project_service.create_sub(db, p, item["content"], t.lang, actor, team_id=team_id, worker=worker,
                                         slot=slot if team_id == team.id and worker is None else None,
                                         recorded_at=occ_utc, inspection_id=t.id, log_user=user_id)
        old = done_before.get(item["content"].strip())
        if old is not None:
            for l in LANGS:
                setattr(sub, f"content_{l}", getattr(old, f"content_{l}"))
            sub.source_lang, sub.translation_status = old.source_lang, "done"
    run.project_id = p.id
    db.add(run)
    audit.log(db, user_id=user_id, action="auto_create" if user_id is None else "create", entity="project",
              entity_id=p.id, new={"inspection_id": t.id, "inspection": t.name, "occurrence": occ_local.isoformat(),
                                    "team_id": team.id, "subs": len(t.sub_items)})


def process_template(db: Session, t: InspectionTemplate, now_local: datetime) -> list[InspectionRun]:
    """处理一个到期的巡查项：错过多次时只派最近一次。"""
    rule, sched = rule_of(t), load_schedule(db)
    due = [to_local(t.next_run_at)]
    while len(due) < MAX_CATCHUP:
        nxt = next_occurrence(rule, due[-1], sched)
        if nxt is None or nxt > now_local:
            break
        due.append(nxt)
    runs = []
    for occ in due[:-1]:  # 较早错过的：只记录，不派
        runs.append(InspectionRun(template_id=t.id, occurrence_at=to_utc(occ), status="skipped",
                                  note="missed while the server was down", created_at=utcnow()))
        db.add(runs[-1])
    runs.append(create_task(db, t, due[-1]))
    t.last_run_at = to_utc(due[-1])
    schedule_next(db, t, max(now_local, due[-1]))
    return runs


def run_due() -> int:
    """定时任务入口：处理所有到期的巡查项。返回生成的任务数。"""
    now_utc = utcnow()
    now_local = to_local(now_utc)
    with SessionLocal() as db:
        ids = db.scalars(select(InspectionTemplate.id).where(
            InspectionTemplate.enabled.is_(True), InspectionTemplate.next_run_at <= now_utc)).all()
    created = 0
    new_tasks: list[int] = []
    new_projects: list[int] = []
    for tid in ids:
        with SessionLocal() as db:
            t = db.get(InspectionTemplate, tid)
            if t is None or not t.enabled or t.next_run_at is None:
                continue
            try:
                runs = process_template(db, t, now_local)
                db.commit()
            except IntegrityError:
                # 同一次已经派过（例如两个进程同时跑）：只把下次时间往后推
                db.rollback()
                t = db.get(InspectionTemplate, tid)
                schedule_next(db, t, now_local)
                db.commit()
                continue
            except Exception:  # noqa: BLE001  一个巡查项出错不影响其他的
                db.rollback()
                log.exception("inspection %s failed", tid)
                continue
            for r in runs:
                if r.task_id:
                    created += 1
                    new_tasks.append(r.task_id)
                if r.project_id:
                    created += 1
                    new_projects.append(r.project_id)
    for task_id in new_tasks:
        translation_service.enqueue(task_id)
    for pid in new_projects:
        enqueue_project_translations(pid)
    return created


def enqueue_project_translations(project_id: int) -> None:
    """项目名称和还没翻译的子项目放进翻译队列。"""
    from .models import Project

    with SessionLocal() as db:
        p = db.get(Project, project_id)
        pending = p is not None and p.translation_status == "pending"
        ids = db.scalars(select(Task.id).where(Task.project_id == project_id, Task.translation_status == "pending")).all()
    if pending:
        translation_service.enqueue_project(project_id)
    for tid in ids:
        translation_service.enqueue(tid)
