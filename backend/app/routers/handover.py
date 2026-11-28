"""交接班：移交、废弃、早班会视图、未闭环警示设置。

移交：原任务状态改为「已移交」（不可再改），在接收班组生成一条新任务，
source_task_id 指回原任务；内容、译文、图片带过去，参与人员不带（换了班组）。
交接说明作为新任务的「遗留问题」，没填就沿用原任务的遗留问题。
"""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import app_settings, audit, departments, inspection_service, translation_service
from ..departments import get_dept
from ..db import get_db
from ..models import Attachment, AppSetting, Task, TaskHandover, Team, User, utcnow
from ..schedule_service import load_schedule, local_now
from ..schemas import (
    BoardOut,
    DiscardRequest,
    HandoverDefault,
    HandoverRequest,
    SettingsIO,
    TaskOut,
)
from ..security import get_current_user, require_admin
from ..shifts import TeamInfo
from .. import permissions
from .tasks import LANGS, OPEN, _get_task, _require, can_transfer, overdue_clause, tasks_out, visible_now

router = APIRouter(prefix="/api", tags=["handover"])


def _team_info(sched, team_id: int) -> TeamInfo:
    for t in sched.teams:
        if t.id == team_id:
            return t
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")


@router.get("/handover/default", response_model=HandoverDefault)
def handover_default(team_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    sched = load_schedule(db)
    tgt = sched.default_handover_target(_team_info(sched, team_id), local_now())
    return HandoverDefault(team_id=team_id, to_team_id=tgt.id if tgt else None)


@router.post("/handover", response_model=list[TaskOut])
def handover(body: HandoverRequest, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    lang = body.lang or user.lang
    note = (body.note or "").strip() or None
    if body.to_team_id is not None and db.get(Team, body.to_team_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")

    tasks = [_get_task(db, tid) for tid in dict.fromkeys(body.task_ids)]
    for t in tasks:
        if t.status not in OPEN:
            raise HTTPException(status.HTTP_409_CONFLICT, f"task {t.id} is {t.status}")
        if not can_transfer(t):
            raise HTTPException(status.HTTP_409_CONFLICT, "this task cannot be handed over")
        _require(db, t, user, "handover")

    created = perform_handover(db, tasks, body.to_team_id, note, lang, user.id)
    db.commit()
    for t in created:
        if t.translation_status == "pending":
            translation_service.enqueue(t.id)
    return tasks_out(db, [_get_task(db, t.id) for t in created], user)


def perform_handover(db: Session, tasks: list[Task], to_team_id: int | None, note: str | None, lang: str,
                     actor_id: int, auto: bool = False) -> list[Task]:
    """把一批未完成的任务移交出去（不 commit）。to_team_id 为空 = 按交接顺序的默认接班班组。
    auto=True：系统自动移交（项目子项目下班没做完），留痕的操作人记为「系统」，移交记录的操作人记为 actor_id。"""
    sched = load_schedule(db)
    now_local = local_now()
    now = utcnow()
    log_user = None if auto else actor_id
    created: list[Task] = []
    for src in tasks:
        default = sched.default_handover_target(_team_info(sched, src.team_id), now_local)
        target = to_team_id or (default.id if default else None)
        if target is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "no target team")
        if target == src.team_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot hand over to the same team")
        rd, rk = sched.receiving_slot(_team_info(sched, target), now_local)

        new = Task(
            client_id=str(uuid.uuid4()),
            content_zh=src.content_zh, content_sr=src.content_sr, content_en=src.content_en,
            source_lang=src.source_lang, translation_status=src.translation_status,
            team_id=target, origin_team_id=src.origin_team_id, source_task_id=src.id,
            inspection_id=src.inspection_id, project_id=src.project_id, equipment_id=src.equipment_id, kind=src.kind,
            status=src.status, shift_date=rd, shift_kind=rk, start_at=src.start_at,
            created_by=actor_id, updated_by=actor_id, recorded_at=now, created_at=now, updated_at=now,
            chain_started_at=src.chain_started_at, handover_count=src.handover_count + 1,
            manual_fields=[m for m in (src.manual_fields or []) if not m.startswith("leftover_")]
            if note else list(src.manual_fields or []),
        )
        if note:
            setattr(new, f"leftover_{lang}", note)
            new.leftover_source_lang = lang
        else:
            for l in LANGS:
                setattr(new, f"leftover_{l}", getattr(src, f"leftover_{l}"))
            new.leftover_source_lang = src.leftover_source_lang
        translation_service.refresh_status(new)
        db.add(new)
        db.flush()

        # 图片带过去：新建记录指向同一批文件
        for a in src.attachments:
            db.add(Attachment(
                client_id=str(uuid.uuid4()), task_id=new.id, filename=a.filename,
                content_type=a.content_type, size=a.size, width=a.width, height=a.height,
                path_original=a.path_original, path_view=a.path_view, path_thumb=a.path_thumb,
                taken_at=a.taken_at, taken_at_source=a.taken_at_source,
                uploaded_by=a.uploaded_by, uploaded_at=a.uploaded_at,
            ))

        db.add(TaskHandover(
            from_task_id=src.id, to_task_id=new.id, from_team_id=src.team_id, to_team_id=target,
            default_team_id=default.id if default else None, note=note, note_lang=lang if note else None,
            by_user_id=actor_id, at=now,
        ))
        extra = {"to_task_id": new.id, "to_team_id": target,
                 "default_team_id": default.id if default else None, "note": note, "auto": auto}
        audit.log_changes(db, src, {"status": "handed_over"}, user_id=log_user, entity="task",
                          entity_id=src.id, action="handover")
        audit.log(db, user_id=log_user, action="handover", entity="task", entity_id=src.id,
                  field="to_team", new=target, extra=extra)
        src.updated_by = actor_id
        src.updated_at = now
        audit.log(db, user_id=log_user, action="receive", entity="task", entity_id=new.id,
                  new={"from_task_id": src.id, "from_team_id": src.team_id, "to_team_id": target,
                       "shift": f"{rd} {rk}", "note": note},
                  extra={"handover_count": new.handover_count, "auto": auto})
        created.append(new)
    return created


@router.post("/tasks/{task_id}/discard", response_model=TaskOut)
def discard(task_id: int, body: DiscardRequest, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    task = _get_task(db, task_id)
    if task.status not in OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}")
    _require(db, task, user, "discard")
    if task.status not in OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}")
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reason required")
    lang = body.lang or user.lang
    now = utcnow()
    changes = {"status": "discarded", f"discard_reason_{lang}": reason, "discard_reason_lang": lang,
               "discarded_by": user.id, "discarded_at": now}
    audit.log_changes(db, task, changes, user_id=user.id, entity="task", entity_id=task.id, action="discard")
    translation_service.mark_text_changed(task, "discard_reason")
    task.updated_by = user.id
    task.updated_at = now
    db.commit()
    translation_service.enqueue(task.id)
    return tasks_out(db, [_get_task(db, task.id)], user)[0]


def board_teams(sched, team, d, kind=None) -> list:
    """交接班合并：这个班次里和 team 合并显示的班组（主班组在前）。"""
    return sched.group_of(team, d, kind)


@router.get("/board", response_model=BoardOut)
def board(team_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user),
          dept: int | None = Depends(get_dept)):
    """首页交接班：上一班移交过来的、本班待办、本班完成（不在班时显示它上一个班完成的）。

    不指定班组时：有班组的人看本班组；管理员、车间管理员看当前车间此刻在班的主班组。
    常白班上班的日子，常白班和当天白班的倒班班组合并显示（两边班长都能操作）。
    """
    sched = load_schedule(db)
    now_local = local_now()
    d, k = sched.shift_at(now_local)
    if team_id is None:
        own_team = sched.team(user.team_id) if user.role != "admin" and user.team_id else None
        if own_team is not None and own_team.dept == dept:
            team_id = own_team.id
        else:
            rot = sched.main_team_on(d, k, dept)
            dept_teams = [t for t in sched.teams if t.dept == dept]
            if rot is None and not dept_teams:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "no teams in this department")
            team_id = rot.id if rot else dept_teams[0].id
    w = permissions.who(db, user)
    vis = w.visible_team_ids()
    if vis is not None and team_id not in vis:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team")
    team = _team_info(sched, team_id)
    # 显示这个班组当前在上的班；不在班就显示它的下一个班。合并同一班次的其他班组
    try:
        sd, sk = (d, k) if sched.is_on(team, d, k) else sched.next_shift_of_team(team, d, k)
    except ValueError:  # 不固定班组没安排班：只显示它自己
        sd, sk = d, k
    group = board_teams(sched, team, sd, sk)
    main = group[0]
    ids = [t.id for t in group]
    on_duty = any(sched.is_on(t, d, k) for t in group)
    pd, pk = sched.prev_shift(sd, sk)
    prev_ids = [t.id for t in sched.teams_on(pd, pk, main.dept) if t.id not in ids]
    nxt = sched.default_handover_target(main, now_local)

    opts = [selectinload(Task.workers), selectinload(Task.attachments), selectinload(Task.lead)]
    open_tasks = db.scalars(select(Task).options(*opts).where(Task.team_id.in_(ids), Task.status.in_(OPEN), visible_now())
                            .order_by(Task.chain_started_at)).all()
    # 本班完成：在班 → 这个班次开始以来；不在班 → 它最近一个已经上过的班次
    dd, dk = d, k
    if not on_duty:
        dd, dk = sched.prev_shift(d, k)
        for _ in range(30 * 3):
            if any(sched.is_on(t, dd, dk) for t in group):
                break
            dd, dk = sched.prev_shift(dd, dk)
    w0, w1 = sched.shift_window(dd, dk)
    done = db.scalars(select(Task).options(*opts).where(
        Task.team_id.in_(ids), Task.status == "done",
        Task.confirmed_at >= inspection_service.to_utc(w0), Task.confirmed_at < inspection_service.to_utc(w1))
        .order_by(Task.confirmed_at.desc())).all()

    all_out = tasks_out(db, [*open_tasks, *done], user)
    by_id = {t.id: t for t in all_out}
    open_out = [by_id[t.id] for t in open_tasks]
    key = lambda t: (not t.overdue, t.chain_started_at)  # 超时的排最前
    # 「小项目由当班自己添加」的项目（例如停送电）：这个班的，本班往里加小项目
    from .. import project_service
    from ..models import Project
    from ..schemas import BoardProject, Trilingual

    # 这个班的；刚下班 2 小时内（补录期）的也还显示
    sd_start = sched.shift_window(sd, sk)[0]
    # 项目像一个文件夹放在「本班待办」里（全做完了放「本班完成」），它的小项目不再一条条出现在交接班里
    projs = [p for p in db.scalars(select(Project).where(Project.open_items.is_(True), Project.closed_empty.is_(False),
                                                         Project.team_id.in_(ids), Project.shift_date.is_not(None))
                                   .order_by(Project.id))
             if (p.shift_date, p.shift_kind) == (sd, sk)
             or (p.closed_at is None and sched.shift_window(p.shift_date, p.shift_kind)[0] < sd_start
                 and sched.shift_window(p.shift_date, p.shift_kind)[1] + timedelta(hours=2) >= now_local)]
    prog = project_service.progress(db, [p.id for p in projs])
    board_projects = [BoardProject(
        id=p.id, name=Trilingual(zh=p.name_zh, sr=p.name_sr, en=p.name_en), source_lang=p.source_lang, team_id=p.team_id,
        shift_date=p.shift_date, shift_kind=p.shift_kind, total=prog[p.id].total, done=prog[p.id].done,
        open=prog[p.id].open, closed=p.closed_at is not None,
        can_add=p.closed_at is None and (w.team_ok("project.manage", p.team_id) or w.team_ok("task.create", p.team_id)))
        for p in projs]
    in_folder = {p.id for p in projs}
    open_out = [t for t in open_out if not (t.project and t.project.id in in_folder)]
    done_out = [by_id[t.id] for t in done if not (t.project_id and t.project_id in in_folder)]
    return BoardOut(
        projects=board_projects,
        team_id=main.id, team_ids=ids, shift_date=sd, shift_kind=sk, on_duty=on_duty,
        prev_team_ids=prev_ids, next_team_id=nxt.id if nxt else None,
        received=sorted([t for t in open_out if t.handover_in and t.handover_in.team_id not in ids], key=key),
        todo=sorted([t for t in open_out if not (t.handover_in and t.handover_in.team_id not in ids)], key=key),
        done_recent=done_out, done_shift_date=dd, done_shift_kind=dk,
    )


@router.get("/overdue", response_model=list[TaskOut])
def overdue(db: Session = Depends(get_db), user: User = Depends(get_current_user),
            dept: int | None = Depends(get_dept)):
    """首页未闭环警示：当前车间所有班组的超时任务，本班组的排最前。"""
    rows = db.scalars(select(Task).options(selectinload(Task.workers), selectinload(Task.attachments))
                      .where(overdue_clause(db, utcnow()), Task.team_id.in_(departments.team_ids(db, dept)))
                      .order_by(Task.chain_started_at).limit(200)).all()
    vis = permissions.who(db, user).visible_team_ids()
    if vis is not None:  # 只能看本班组的，只显示本班组（和合并班组）的超时任务
        rows = [t for t in rows if t.team_id in vis]
    rows = sorted(rows, key=lambda t: t.team_id != user.team_id)
    return tasks_out(db, rows, user)


@router.get("/settings", response_model=SettingsIO)
def get_app_settings(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return app_settings.get_all(db)


@router.put("/settings", response_model=SettingsIO)
def put_app_settings(body: SettingsIO, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    current = app_settings.get_all(db)
    for key, value in body.model_dump().items():
        if current[key] == value:
            continue
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        audit.log(db, user_id=admin.id, action="update", entity="setting", entity_id=key,
                  field=key, old=current[key], new=value)
    db.commit()
    return app_settings.get_all(db)
