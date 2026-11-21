"""任务：增删改、参与人员、状态流转、图片。所有改动写留痕。

权限：所有登录用户可查看全部任务；班长只能新建/修改本班组任务，管理员可改全部。
已移交 / 已废弃的任务不可再修改（移交、废弃见 handover.py）。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import app_settings, audit
from ..config import get_settings
from ..db import get_db
from ..images import InvalidImage, parse_exif_datetime, process_upload
from ..models import Attachment, AuditLog, Task, TaskHandover, Team, User, Worker, utcnow
from ..schedule_service import load_schedule
from ..schemas import (
    AttachmentOut,
    AuditOut,
    HandoverInfo,
    HistoryOut,
    TaskCreate,
    TaskOut,
    TaskPage,
    TaskStatusChange,
    TaskUpdate,
    Trilingual,
    WorkerOut,
)
from ..security import file_token, get_current_user, verify_file_token

router = APIRouter(prefix="/api", tags=["tasks"])

LANGS = ("zh", "sr", "en")
TERMINAL = {"handed_over", "discarded"}
OPEN = ("not_started", "in_progress")
TRANSITIONS = {
    "not_started": {"in_progress", "done"},
    "in_progress": {"not_started", "done"},
    "done": {"in_progress"},  # 重新打开
}


# ---------------- 工具 ----------------
def to_utc(d: datetime | None) -> datetime | None:
    """无时区的输入按工厂时区理解，统一转成 UTC。"""
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=get_settings().tz)
    return d.astimezone(timezone.utc)


def _upload_root() -> Path:
    return Path(get_settings().upload_dir)


def _names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(User.id, User.full_name)).all())


def _att_out(a: Attachment, names: dict[int, str]) -> AttachmentOut:
    t = file_token(a.id)
    base = f"/api/files/{a.id}"
    return AttachmentOut(
        id=a.id, client_id=a.client_id, filename=a.filename, width=a.width, height=a.height,
        taken_at=a.taken_at, taken_at_source=a.taken_at_source, uploaded_by=a.uploaded_by,
        uploaded_by_name=names.get(a.uploaded_by, ""), uploaded_at=a.uploaded_at,
        url_thumb=f"{base}/thumb?t={t}", url_view=f"{base}/view?t={t}",
        url_original=f"{base}/original?t={t}",
    )


def _can_edit(task: Task, user: User) -> bool:
    if task.status in TERMINAL:
        return False
    return user.role == "admin" or task.team_id == user.team_id


def _aware(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


@dataclass
class OutCtx:
    """把一批任务转成 TaskOut 时需要的附加数据（一次查询，避免逐条查）。"""

    names: dict[int, str]
    ho_from: dict[int, TaskHandover]  # from_task_id → 移交记录
    ho_to: dict[int, TaskHandover]  # to_task_id → 移交记录
    overdue_hours: int
    overdue_handovers: int
    now: datetime


def make_ctx(db: Session, tasks: list[Task]) -> OutCtx:
    ids = [t.id for t in tasks]
    hos = db.scalars(select(TaskHandover).where(
        or_(TaskHandover.from_task_id.in_(ids), TaskHandover.to_task_id.in_(ids)))).all() if ids else []
    cfg = app_settings.get_all(db)
    return OutCtx(
        names=_names(db),
        ho_from={h.from_task_id: h for h in hos},
        ho_to={h.to_task_id: h for h in hos},
        overdue_hours=cfg["overdue_hours"],
        overdue_handovers=cfg["overdue_handovers"],
        now=utcnow(),
    )


def overdue_clause(db: Session, now: datetime):
    """SQL 条件：未完成且（从第一次录入起超过 N 小时 或 已移交 N 次及以上）。"""
    cfg = app_settings.get_all(db)
    return (Task.status.in_(OPEN)) & or_(
        Task.chain_started_at <= now - timedelta(hours=cfg["overdue_hours"]),
        Task.handover_count >= cfg["overdue_handovers"],
    )


def _ho_info(h: TaskHandover | None, incoming: bool, names: dict[int, str]) -> HandoverInfo | None:
    if h is None:
        return None
    return HandoverInfo(
        team_id=h.from_team_id if incoming else h.to_team_id,
        task_id=h.from_task_id if incoming else h.to_task_id,
        default_team_id=h.default_team_id, note=h.note, note_lang=h.note_lang,
        by_name=names.get(h.by_user_id, ""), at=h.at,
    )


def task_out(task: Task, user: User, ctx: OutCtx) -> TaskOut:
    names = ctx.names
    age = (ctx.now - _aware(task.chain_started_at)).total_seconds() / 3600
    overdue = task.status in OPEN and (age >= ctx.overdue_hours or task.handover_count >= ctx.overdue_handovers)
    return TaskOut(
        id=task.id, client_id=task.client_id,
        content=Trilingual(zh=task.content_zh, sr=task.content_sr, en=task.content_en),
        source_lang=task.source_lang,
        leftover=Trilingual(zh=task.leftover_zh, sr=task.leftover_sr, en=task.leftover_en),
        leftover_source_lang=task.leftover_source_lang,
        translation_status=task.translation_status,
        team_id=task.team_id, origin_team_id=task.origin_team_id, source_task_id=task.source_task_id,
        status=task.status, shift_date=task.shift_date, shift_kind=task.shift_kind,
        start_at=task.start_at, end_at=task.end_at,
        confirmed_by=task.confirmed_by,
        confirmed_by_name=names.get(task.confirmed_by) if task.confirmed_by else None,
        confirmed_at=task.confirmed_at,
        created_by=task.created_by, created_by_name=names.get(task.created_by, ""),
        updated_by=task.updated_by, updated_by_name=names.get(task.updated_by, ""),
        recorded_at=task.recorded_at, created_at=task.created_at, updated_at=task.updated_at,
        workers=[WorkerOut.model_validate(w) for w in task.workers],
        attachments=[_att_out(a, names) for a in task.attachments],
        can_edit=_can_edit(task, user),
        chain_started_at=task.chain_started_at, handover_count=task.handover_count,
        age_hours=round(age, 1), overdue=overdue,
        handover_in=_ho_info(ctx.ho_to.get(task.id), True, names),
        handover_out=_ho_info(ctx.ho_from.get(task.id), False, names),
        discard_reason=Trilingual(zh=task.discard_reason_zh, sr=task.discard_reason_sr, en=task.discard_reason_en),
        discard_reason_lang=task.discard_reason_lang,
        discarded_by_name=names.get(task.discarded_by) if task.discarded_by else None,
        discarded_at=task.discarded_at,
    )


def tasks_out(db: Session, tasks: list[Task], user: User) -> list[TaskOut]:
    ctx = make_ctx(db, tasks)
    return [task_out(t, user, ctx) for t in tasks]


def one_out(db: Session, task: Task, user: User) -> TaskOut:
    return tasks_out(db, [task], user)[0]


def _get_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id, options=[selectinload(Task.workers), selectinload(Task.attachments)])
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return task


def _require_edit(task: Task, user: User) -> None:
    if task.status in TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}")
    if not _can_edit(task, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's task")


def _load_workers(db: Session, ids: list[int]) -> list[Worker]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    ws = db.scalars(select(Worker).where(Worker.id.in_(ids))).all()
    if len(ws) != len(ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown worker")
    by_id = {w.id: w for w in ws}
    return [by_id[i] for i in ids]


def _check_times(start: datetime | None, end: datetime | None) -> None:
    if start and end and to_utc(end) < to_utc(start):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_at before start_at")


def _text_changes(prefix: str, task: Task, text: str | None, lang: str) -> dict:
    """修改某个语言的文字：写入该语言列，其余两种语言清空待重新翻译。"""
    src_field = "source_lang" if prefix == "content" else "leftover_source_lang"
    text = (text or "").strip() or None
    if text is None:  # 只有遗留问题允许清空
        return {f"{prefix}_{l}": None for l in LANGS} | {src_field: None}
    if getattr(task, f"{prefix}_{lang}") == text and getattr(task, src_field) == lang:
        return {}
    changes = {f"{prefix}_{l}": None for l in LANGS if l != lang}
    changes[f"{prefix}_{lang}"] = text
    changes[src_field] = lang
    return changes


# ---------------- 任务 ----------------
@router.get("/tasks", response_model=TaskPage)
def list_tasks(
    team_id: int | None = None,
    status_: list[str] | None = Query(default=None, alias="status"),
    date_from: str | None = None,
    date_to: str | None = None,
    worker_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
    overdue: bool = False,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Task)
    if team_id:
        query = query.where(Task.team_id == team_id)
    if status_:
        query = query.where(Task.status.in_(status_))
    if date_from:
        query = query.where(Task.shift_date >= date_from)
    if date_to:
        query = query.where(Task.shift_date <= date_to)
    if worker_id:
        query = query.where(Task.workers.any(Worker.id == worker_id))
    if overdue:
        query = query.where(overdue_clause(db, utcnow()))
    if q:
        like = f"%{q}%"
        query = query.where(or_(*[getattr(Task, f"{p}_{l}").ilike(like)
                                  for p in ("content", "leftover") for l in LANGS]))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.options(selectinload(Task.workers), selectinload(Task.attachments))
        .order_by(Task.shift_date.desc(), Task.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    return TaskPage(items=tasks_out(db, list(rows), user), total=total)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return one_out(db, _get_task(db, task_id), user)


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 离线草稿可能重复提交：同一个 client_id 直接返回已有任务
    existing = db.scalar(select(Task).where(Task.client_id == body.client_id))
    if existing is not None:
        # 真正的重试内容一定相同；内容不同说明客户端出错，拒绝而不是悄悄返回别的任务
        same = existing.created_by == user.id and \
            getattr(existing, f"content_{body.lang}") == body.content.strip()
        if not same:
            raise HTTPException(status.HTTP_409_CONFLICT, "client_id already used")
        return one_out(db, _get_task(db, existing.id), user)

    if user.role == "admin":
        if body.team_id is None or db.get(Team, body.team_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "team_id required")
        team_id = body.team_id
    else:
        team_id = user.team_id

    now = utcnow()
    recorded = to_utc(body.recorded_at) or now
    if not (now - timedelta(days=30) <= recorded <= now + timedelta(minutes=5)):
        recorded = now
    local = recorded.astimezone(get_settings().tz).replace(tzinfo=None)
    shift_date, shift_kind = load_schedule(db).shift_at(local)

    _check_times(body.start_at, body.end_at)
    start_at, end_at = to_utc(body.start_at), to_utc(body.end_at)
    if body.status in ("in_progress", "done") and start_at is None:
        start_at = recorded
    if body.status == "done" and end_at is None:
        end_at = max(recorded, start_at)

    task = Task(
        client_id=body.client_id, source_lang=body.lang, team_id=team_id, origin_team_id=team_id,
        status=body.status, shift_date=shift_date, shift_kind=shift_kind,
        start_at=start_at, end_at=end_at,
        confirmed_by=user.id if body.status == "done" else None,
        confirmed_at=now if body.status == "done" else None,
        created_by=user.id, updated_by=user.id, recorded_at=recorded, created_at=now, updated_at=now,
        translation_status="pending", chain_started_at=recorded, handover_count=0,
    )
    setattr(task, f"content_{body.lang}", body.content.strip())
    if body.leftover and body.leftover.strip():
        setattr(task, f"leftover_{body.lang}", body.leftover.strip())
        task.leftover_source_lang = body.lang
    task.workers = _load_workers(db, body.worker_ids)
    db.add(task)
    db.flush()
    audit.log(db, user_id=user.id, action="create", entity="task", entity_id=task.id, new={
        "content": body.content.strip(), "lang": body.lang, "team_id": team_id,
        "status": body.status, "worker_ids": [w.id for w in task.workers],
        "start_at": start_at, "end_at": end_at, "leftover": task.leftover_source_lang and body.leftover.strip(),
        "recorded_at": recorded, "shift": f"{shift_date} {shift_kind}",
    })
    db.commit()
    return one_out(db, _get_task(db, task.id), user)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    task = _get_task(db, task_id)
    _require_edit(task, user)
    data = body.model_dump(exclude_unset=True)
    lang = body.lang or user.lang
    changes: dict = {}
    if "content" in data:
        if not data["content"] or not data["content"].strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "content required")
        changes |= _text_changes("content", task, data["content"], lang)
    if "leftover" in data:
        changes |= _text_changes("leftover", task, data["leftover"], body.leftover_lang or lang)
    for f in ("start_at", "end_at"):
        if f in data:
            changes[f] = to_utc(data[f])
    _check_times(changes.get("start_at", task.start_at), changes.get("end_at", task.end_at))

    changed = audit.log_changes(db, task, changes, user_id=user.id, entity="task", entity_id=task.id)
    if any(k.startswith(("content_", "leftover_")) for k in changes) and changed:
        task.translation_status = "pending"

    if "worker_ids" in data and data["worker_ids"] is not None:
        new_workers = _load_workers(db, data["worker_ids"])
        old_ids = [w.id for w in task.workers]
        new_ids = [w.id for w in new_workers]
        if sorted(old_ids) != sorted(new_ids):
            names = dict(db.execute(select(Worker.id, Worker.name)).all())
            audit.log(db, user_id=user.id, action="update", entity="task", entity_id=task.id,
                      field="workers", old=[names[i] for i in old_ids], new=[names[i] for i in new_ids],
                      extra={"old_ids": old_ids, "new_ids": new_ids})
            task.workers = new_workers
            changed = True

    if changed:
        task.updated_by = user.id
        task.updated_at = utcnow()
    db.commit()
    return one_out(db, _get_task(db, task.id), user)


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
def change_status(task_id: int, body: TaskStatusChange, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    task = _get_task(db, task_id)
    _require_edit(task, user)
    new = body.status
    if new == task.status:
        return one_out(db, task, user)
    if new not in TRANSITIONS.get(task.status, set()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"cannot go from {task.status} to {new}")
    now = utcnow()
    changes: dict = {"status": new}
    if new == "in_progress" and task.start_at is None:
        changes["start_at"] = now
    if new == "done":
        if task.end_at is None:
            changes["end_at"] = now
        if task.start_at is None:
            changes["start_at"] = changes.get("end_at", task.end_at)
        changes["confirmed_by"] = user.id
        changes["confirmed_at"] = now
    if task.status == "done":  # 重新打开：清除完成信息
        changes |= {"end_at": None, "confirmed_by": None, "confirmed_at": None}
    if new == "not_started":
        changes["start_at"] = None
    audit.log_changes(db, task, changes, user_id=user.id, entity="task", entity_id=task.id,
                      action="status")
    task.updated_by = user.id
    task.updated_at = now
    db.commit()
    return one_out(db, _get_task(db, task.id), user)


@router.get("/tasks/{task_id}/history", response_model=list[HistoryOut])
def task_history(task_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _get_task(db, task_id)
    names = _names(db)
    rows = db.scalars(select(AuditLog).where(AuditLog.entity == "task", AuditLog.entity_id == str(task_id))
                      .order_by(AuditLog.id)).all()
    return [HistoryOut(**AuditOut.model_validate(r).model_dump(), user_name=names.get(r.user_id))
            for r in rows]


# ---------------- 图片 ----------------
@router.post("/tasks/{task_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    task_id: int,
    file: UploadFile = File(...),
    client_id: str = Form(..., pattern=r"^[0-9a-fA-F-]{36}$"),
    last_modified: int | None = Form(default=None),  # 浏览器 File.lastModified（毫秒）
    exif_datetime: str | None = Form(default=None, max_length=40),  # 手机压缩前读出的 EXIF 拍摄时间
    exif_offset: str | None = Form(default=None, max_length=10),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = get_settings()
    names = _names(db)
    existing = db.scalar(select(Attachment).where(Attachment.client_id == client_id))
    if existing is not None:
        if existing.task_id != task_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "client_id already used")
        return _att_out(existing, names)

    task = _get_task(db, task_id)
    _require_edit(task, user)
    if len(task.attachments) >= s.max_photos_per_task:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "too many photos")
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file too large")

    now = utcnow()
    mtime = datetime.fromtimestamp(last_modified / 1000, timezone.utc) if last_modified else None
    try:
        p = process_upload(data, _upload_root(), s.tz, mtime, now,
                           client_exif=parse_exif_datetime(exif_datetime, exif_offset, s.tz))
    except InvalidImage:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not a supported image")

    a = Attachment(
        client_id=client_id, task_id=task.id, filename=(file.filename or "photo")[:255],
        content_type=p.content_type, size=len(data), width=p.width, height=p.height,
        path_original=p.original_rel, path_view=p.view_rel, path_thumb=p.thumb_rel,
        taken_at=p.taken_at.astimezone(timezone.utc), taken_at_source=p.taken_at_source,
        uploaded_by=user.id, uploaded_at=now,
    )
    db.add(a)
    db.flush()
    audit.log(db, user_id=user.id, action="attach", entity="task", entity_id=task.id,
              field="attachments", new=a.filename,
              extra={"attachment_id": a.id, "taken_at": a.taken_at.isoformat(),
                     "taken_at_source": a.taken_at_source, "size": a.size})
    task.updated_by = user.id
    task.updated_at = now
    db.commit()
    return _att_out(a, names)


@router.delete("/attachments/{att_id}", status_code=204)
def delete_attachment(att_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(Attachment, att_id)
    if a is None or a.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    task = _get_task(db, a.task_id)
    _require_edit(task, user)
    a.deleted_at = utcnow()
    a.deleted_by = user.id
    audit.log(db, user_id=user.id, action="detach", entity="task", entity_id=task.id,
              field="attachments", old=a.filename, extra={"attachment_id": a.id})
    task.updated_by = user.id
    task.updated_at = a.deleted_at
    db.commit()


@router.get("/files/{att_id}/{variant}", include_in_schema=False)
def get_file(att_id: int, variant: str, t: str, db: Session = Depends(get_db)):
    if variant not in ("thumb", "view", "original") or not verify_file_token(t, att_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    a = db.get(Attachment, att_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    rel = {"thumb": a.path_thumb, "view": a.path_view, "original": a.path_original}[variant]
    path = _upload_root() / rel
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    media = "image/jpeg" if variant != "original" else a.content_type
    filename = a.filename if variant == "original" else None
    return FileResponse(path, media_type=media, filename=filename,
                        headers={"Cache-Control": "private, max-age=43200"})
