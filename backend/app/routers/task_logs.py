"""任务的班次日志：每条任务可以随时加多条自由填写的记录，自动翻译成另外两种语言。

- 属于哪个班次按写的时间算（离线写的按写的时间，最多往前 3 天）
- 看：能看到这条任务的人都能看；列出整条移交链（这条任务和它移交前的各条）上的日志，下一班能看到前面各班写的
- 写：能开始 / 完成或修改这条任务的人（task_perms 的 log）；已移交 / 已废弃的任务不能再写（写在接收的那条上）
- 删：写的人自己，或能修改这条任务的人；软删除并留痕
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, permissions, translation_service, translator
from ..db import get_db
from ..models import Task, TaskLog, User, Worker, utcnow
from ..schedule_service import load_schedule
from ..schemas import Lang, Trilingual, UTCDateTime
from ..security import get_current_user
from .tasks import TERMINAL, _get_task, _visible, task_perms, to_utc

router = APIRouter(prefix="/api", tags=["task-logs"])
UUID = r"^[0-9a-fA-F-]{36}$"


class LogIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    lang: Lang  # 录入时的界面语言（暂记，原文语言以模型判断为准）
    client_id: str | None = Field(default=None, pattern=UUID)  # 离线发件箱去重
    recorded_at: datetime | None = None  # 离线时写的时间


class LogOut(BaseModel):
    id: int
    task_id: int
    content: Trilingual
    source_lang: str
    translation_status: str
    shift_date: str
    shift_kind: str
    team_id: int | None
    author: str
    recorded_at: UTCDateTime
    can_delete: bool


def chain_ids(db: Session, task: Task) -> list[int]:
    """这条任务和它移交前的各条（沿 source_task_id 往回找）。"""
    ids, cur = [task.id], task.source_task_id
    while cur and cur not in ids and len(ids) < 100:
        ids.append(cur)
        cur = db.scalar(select(Task.source_task_id).where(Task.id == cur))
    return ids


def _can_delete(w: "permissions.Who", task: Task, x: TaskLog) -> bool:
    if w.user.role == "admin":
        return True
    if task.status in TERMINAL:
        return False
    return x.created_by == w.user.id or w.task_ok("task.edit", task)


def _out(x: TaskLog, task: Task, w, names: dict) -> LogOut:
    return LogOut(id=x.id, task_id=x.task_id, content=Trilingual(zh=x.content_zh, sr=x.content_sr, en=x.content_en),
                  source_lang=x.source_lang, translation_status=x.translation_status,
                  shift_date=str(x.shift_date), shift_kind=x.shift_kind, team_id=x.team_id,
                  author=names.get(("w", x.worker_id)) or names.get(("u", x.created_by)) or "",
                  recorded_at=x.recorded_at, can_delete=_can_delete(w, task, x))


def _names(db: Session, rows: list[TaskLog]) -> dict:
    wids = {x.worker_id for x in rows if x.worker_id}
    uids = {x.created_by for x in rows}
    out = {}
    if wids:
        out |= {("w", i): n for i, n in db.execute(select(Worker.id, Worker.name).where(Worker.id.in_(wids)))}
    if uids:
        out |= {("u", u.id): u.full_name or u.username for u in db.scalars(select(User).where(User.id.in_(uids)))}
    return out


@router.get("/tasks/{task_id}/logs", response_model=list[LogOut])
def list_logs(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = _get_task(db, task_id)
    w = permissions.who(db, user)
    if not _visible(w, task):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's task")
    ids = chain_ids(db, task)
    rows = list(db.scalars(select(TaskLog).where(TaskLog.task_id.in_(ids), TaskLog.deleted_at.is_(None))
                           .order_by(TaskLog.recorded_at, TaskLog.id)))
    tasks = {t.id: t for t in db.scalars(select(Task).where(Task.id.in_(ids)))}
    names = _names(db, rows)
    return [_out(x, tasks[x.task_id], w, names) for x in rows]


@router.post("/tasks/{task_id}/logs", response_model=LogOut, status_code=201)
def add_log(task_id: int, body: LogIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = _get_task(db, task_id)
    w = permissions.who(db, user)
    text = body.content.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "content is empty")
    if body.lang == "sr":
        text = translator.to_latin(text)
    if body.client_id:  # 离线草稿重复提交：同一条直接返回，内容不同则拒绝
        old = db.scalar(select(TaskLog).where(TaskLog.client_id == body.client_id))
        if old is not None:
            # 原文语言可能已被模型改判，所以三列里有一列一样就算同一条
            if old.task_id != task.id or text not in (old.content_zh, old.content_sr, old.content_en):
                raise HTTPException(status.HTTP_409_CONFLICT, "client_id already used")
            return _out(old, task, w, _names(db, [old]))
    if task.status in TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}")
    if not task_perms(w, task)["log"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's task")
    now = utcnow()
    at = now
    if body.recorded_at is not None:  # 离线写的：按写的时间，但不晚于现在、不早于 3 天前
        at = min(max(to_utc(body.recorded_at), now - timedelta(days=3)), now)
    sched = load_schedule(db)
    from ..config import get_settings

    local = at.astimezone(get_settings().tz).replace(tzinfo=None)
    d, k = sched.shift_at(local)
    x = TaskLog(task_id=task.id, client_id=body.client_id, source_lang=body.lang, translation_status="pending",
                shift_date=d, shift_kind=k, team_id=task.team_id, worker_id=w.worker_id, created_by=user.id,
                recorded_at=at, created_at=now)
    setattr(x, f"content_{body.lang}", text)
    db.add(x)
    db.flush()
    audit.log(db, user_id=user.id, action="log", entity="task", entity_id=task.id, field="log",
              new=text, extra={"log_id": x.id, "lang": body.lang, "shift": f"{d} {k}"})
    db.commit()
    translation_service.enqueue_log(x.id)
    db.refresh(x)
    return _out(x, task, w, _names(db, [x]))


@router.delete("/task-logs/{log_id}", status_code=204)
def delete_log(log_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    x = db.get(TaskLog, log_id)
    if x is None or x.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    task = _get_task(db, x.task_id)
    if not _can_delete(permissions.who(db, user), task, x):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's task")
    x.deleted_at, x.deleted_by = utcnow(), user.id
    audit.log(db, user_id=user.id, action="log_delete", entity="task", entity_id=task.id, field="log",
              old=getattr(x, f"content_{x.source_lang}"), extra={"log_id": x.id})
    db.commit()
