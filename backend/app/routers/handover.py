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

from .. import app_settings, audit, translation_service
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
from .tasks import LANGS, OPEN, _get_task, _require_edit, overdue_clause, tasks_out

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
    sched = load_schedule(db)
    now_local = local_now()
    now = utcnow()
    lang = body.lang or user.lang
    note = (body.note or "").strip() or None
    if body.to_team_id is not None and db.get(Team, body.to_team_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")

    tasks = [_get_task(db, tid) for tid in dict.fromkeys(body.task_ids)]
    for t in tasks:
        _require_edit(t, user)
        if t.status not in OPEN:
            raise HTTPException(status.HTTP_409_CONFLICT, f"task {t.id} is {t.status}")

    created: list[Task] = []
    for src in tasks:
        default = sched.default_handover_target(_team_info(sched, src.team_id), now_local)
        to_team_id = body.to_team_id or (default.id if default else None)
        if to_team_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "no target team")
        if to_team_id == src.team_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot hand over to the same team")
        rd, rk = sched.receiving_slot(_team_info(sched, to_team_id), now_local)

        new = Task(
            client_id=str(uuid.uuid4()),
            content_zh=src.content_zh, content_sr=src.content_sr, content_en=src.content_en,
            source_lang=src.source_lang, translation_status=src.translation_status,
            team_id=to_team_id, origin_team_id=src.origin_team_id, source_task_id=src.id,
            status=src.status, shift_date=rd, shift_kind=rk, start_at=src.start_at,
            created_by=user.id, updated_by=user.id, recorded_at=now, created_at=now, updated_at=now,
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
            from_task_id=src.id, to_task_id=new.id, from_team_id=src.team_id, to_team_id=to_team_id,
            default_team_id=default.id if default else None, note=note, note_lang=lang if note else None,
            by_user_id=user.id, at=now,
        ))
        extra = {"to_task_id": new.id, "to_team_id": to_team_id,
                 "default_team_id": default.id if default else None, "note": note}
        audit.log_changes(db, src, {"status": "handed_over"}, user_id=user.id, entity="task",
                          entity_id=src.id, action="handover")
        audit.log(db, user_id=user.id, action="handover", entity="task", entity_id=src.id,
                  field="to_team", new=to_team_id, extra=extra)
        src.updated_by = user.id
        src.updated_at = now
        audit.log(db, user_id=user.id, action="receive", entity="task", entity_id=new.id,
                  new={"from_task_id": src.id, "from_team_id": src.team_id, "to_team_id": to_team_id,
                       "shift": f"{rd} {rk}", "note": note},
                  extra={"handover_count": new.handover_count})
        created.append(new)

    db.commit()
    for t in created:
        if t.translation_status == "pending":
            translation_service.enqueue(t.id)
    return tasks_out(db, [_get_task(db, t.id) for t in created], user)


@router.post("/tasks/{task_id}/discard", response_model=TaskOut)
def discard(task_id: int, body: DiscardRequest, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    task = _get_task(db, task_id)
    _require_edit(task, user)
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


@router.get("/board", response_model=BoardOut)
def board(team_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """早班会 / 交接班视图。"""
    sched = load_schedule(db)
    team = _team_info(sched, team_id)
    now_local = local_now()
    d, k = sched.shift_at(now_local)
    on_duty = sched.is_on(team, d, k)
    sd, sk = (d, k) if on_duty else sched.next_shift_of_team(team, d, k)
    pd, pk = sched.prev_shift(sd, sk)
    prev_ids = [t.id for t in sched.teams_on(pd, pk) if t.id != team_id]
    nxt = sched.default_handover_target(team, now_local)

    opts = [selectinload(Task.workers), selectinload(Task.attachments)]
    open_tasks = db.scalars(select(Task).options(*opts).where(Task.team_id == team_id, Task.status.in_(OPEN))
                            .order_by(Task.chain_started_at)).all()
    since = utcnow() - timedelta(hours=12)
    done = db.scalars(select(Task).options(*opts).where(
        Task.team_id == team_id, Task.status == "done", Task.confirmed_at >= since)
        .order_by(Task.confirmed_at.desc())).all()
    out = db.scalars(select(Task).options(*opts).join(TaskHandover, TaskHandover.from_task_id == Task.id).where(
        Task.team_id == team_id, TaskHandover.at >= since).order_by(TaskHandover.at.desc())).all()

    all_out = tasks_out(db, [*open_tasks, *done, *out], user)
    by_id = {t.id: t for t in all_out}
    open_out = [by_id[t.id] for t in open_tasks]
    key = lambda t: (not t.overdue, t.chain_started_at)  # 超时的排最前
    return BoardOut(
        team_id=team_id, shift_date=sd, shift_kind=sk, on_duty=on_duty,
        prev_team_ids=prev_ids, next_team_id=nxt.id if nxt else None,
        received=sorted([t for t in open_out if t.handover_in], key=key),
        todo=sorted([t for t in open_out if not t.handover_in], key=key),
        done_recent=[by_id[t.id] for t in done],
        handed_out_recent=[by_id[t.id] for t in out],
    )


@router.get("/overdue", response_model=list[TaskOut])
def overdue(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """首页未闭环警示：所有班组的超时任务，本班组的排最前。"""
    rows = db.scalars(select(Task).options(selectinload(Task.workers), selectinload(Task.attachments))
                      .where(overdue_clause(db, utcnow())).order_by(Task.chain_started_at).limit(200)).all()
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
