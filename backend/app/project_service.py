"""项目和子项目。

子项目就是普通任务（tasks.project_id）。一个子项目移交后，原任务变「已移交」、接班班组得到一条新任务（也带 project_id），
所以统计时只看「没被移交出去」的那条（链条的最新一条）。
项目完成 = 每个子项目都已完成或已废弃。
可移交的项目：子项目所在班次结束 AUTO_GRACE 分钟后还没做完、而且那个班组现在不在班，系统自动移交给此刻在班的班组。
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import attendance_service as att
from . import audit, translation_service
from .db import SessionLocal
from .models import Project, Task, Worker, utcnow
from .schedule_service import load_schedule, local_now
from .worker_history import Timelines

OPEN = ("not_started", "in_progress")
AUTO_GRACE = timedelta(minutes=30)


@dataclass
class Progress:
    total: int = 0
    done: int = 0
    discarded: int = 0

    @property
    def open(self) -> int:
        return self.total - self.done - self.discarded

    @property
    def closed(self) -> bool:
        return self.total > 0 and self.open == 0


def progress(db: Session, project_ids: list[int]) -> dict[int, Progress]:
    out = {pid: Progress() for pid in project_ids}
    if not project_ids:
        return out
    rows = db.execute(select(Task.project_id, Task.status, func.count()).where(
        Task.project_id.in_(project_ids), Task.status != "handed_over").group_by(Task.project_id, Task.status)).all()
    for pid, st, n in rows:
        p = out[pid]
        p.total += n
        if st == "done":
            p.done += n
        elif st == "discarded":
            p.discarded += n
    return out


def refresh_closed(db: Session, project: Project, prog: Progress | None = None) -> bool:
    """按子项目状态更新项目的完成时间。返回是否有变化。"""
    prog = prog or progress(db, [project.id])[project.id]
    if prog.closed and project.closed_at is None:
        project.closed_at = utcnow()
        audit.log(db, user_id=None, action="close", entity="project", entity_id=project.id,
                  new={"done": prog.done, "discarded": prog.discarded})
        return True
    if not prog.closed and project.closed_at is not None:
        project.closed_at = None  # 又加了子项目 / 重新打开了
        return True
    return False


def next_slot_of_worker(db: Session, sched, worker: Worker, now_local: datetime, days: int = 21) -> tuple[date, str] | None:
    """这个人从现在起下一个（或正在上的）班：按出勤算（含个人排班、调班、请假）。"""
    d0, _k = sched.shift_at(now_local)
    eff = att.effective(db, [worker], d0 - timedelta(days=1), d0 + timedelta(days=days), sched)[worker.id]
    for d in sorted(eff):
        a = eff[d]
        if a.status == "present" and a.shift_kind and sched.shift_window(d, a.shift_kind)[1] > now_local:
            return d, a.shift_kind
    return None


def create_sub(db: Session, project: Project, content: str, lang: str, user_id: int, *, team_id: int | None = None,
               worker: Worker | None = None, slot: tuple[date, str] | None = None, recorded_at: datetime | None = None,
               inspection_id: int | None = None, log_user: int | None | bool = True) -> Task:
    """加一个子项目（不 commit）：分给班组（班长再安排人），或直接分给某个人（带队人 = 这个人）。"""
    sched = load_schedule(db)
    now_local = local_now()
    now = utcnow()
    if worker is not None:
        team_id = Timelines(db, [worker]).on(worker.id, now_local.date()).team_id or worker.team_id
        slot = next_slot_of_worker(db, sched, worker, now_local) or slot
    team = sched.team(team_id)
    if slot is None:
        try:
            slot = sched.receiving_slot(team, now_local) if team else sched.shift_at(now_local)
        except ValueError:  # 不固定班组没安排班：先挂在当前班次
            slot = sched.shift_at(now_local)
    t = Task(
        client_id=str(uuid.uuid4()), source_lang=lang, team_id=team_id, origin_team_id=team_id,
        project_id=project.id, inspection_id=inspection_id, status="not_started", shift_date=slot[0], shift_kind=slot[1],
        created_by=user_id, updated_by=user_id, recorded_at=recorded_at or now, created_at=now, updated_at=now,
        translation_status="pending", chain_started_at=recorded_at or now, handover_count=0, manual_fields=[],
    )
    setattr(t, f"content_{lang}", content.strip())
    if worker is not None:
        t.workers = [worker]
        t.lead_worker_id = worker.id
    db.add(t)
    db.flush()
    audit.log(db, user_id=user_id if log_user is True else log_user, action="create" if log_user is not None else "auto_create",
              entity="task", entity_id=t.id, new={
        "content": content.strip(), "lang": lang, "team_id": team_id, "project_id": project.id,
        "lead_worker_id": worker.id if worker else None, "shift": f"{slot[0]} {slot[1]}"})
    return t


# ---------------- 自动移交 ----------------
def due_for_auto_handover(db: Session, now_local: datetime) -> list[Task]:
    """可移交项目里，所在班次已经结束 AUTO_GRACE 以上、班组现在不在班、还没做完的子项目。"""
    sched = load_schedule(db)
    d, k = sched.shift_at(now_local)
    rows = db.scalars(select(Task).join(Project, Project.id == Task.project_id).where(
        Task.status.in_(OPEN), Project.transferable.is_(True))).all()
    out = []
    for t in rows:
        team = sched.team(t.team_id)
        if team is None or sched.is_on(team, d, k):
            continue
        end = sched.shift_window(t.shift_date, t.shift_kind)[1]
        if now_local >= end + AUTO_GRACE:
            out.append(t)
    return out


def auto_handover(db: Session, now_local: datetime | None = None) -> list[Task]:
    """把到时间的子项目移交给此刻在班的主班组（不 commit 之外的事都在这里做完；返回新任务）。"""
    from .routers.handover import perform_handover

    now_local = now_local or local_now()
    sched = load_schedule(db)
    d, k = sched.shift_at(now_local)
    target = sched.main_team_on(d, k)
    created = []
    for t in due_for_auto_handover(db, now_local):
        if target is None or target.id == t.team_id:
            continue
        actor = t.project.updated_by if t.project else t.updated_by
        created += perform_handover(db, [t], target.id, None, t.source_lang, actor, auto=True)
    return created


def auto_handover_job() -> None:
    """定时任务（每分钟）。"""
    import logging

    try:
        with SessionLocal() as db:
            created = auto_handover(db)
            if created:
                db.commit()
                for t in created:
                    if t.translation_status == "pending":
                        translation_service.enqueue(t.id)
    except Exception:  # noqa: BLE001 —— 定时任务出错不能把调度器弄停
        logging.getLogger("projects").exception("auto handover failed")
