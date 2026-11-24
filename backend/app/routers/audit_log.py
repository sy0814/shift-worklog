"""操作记录（管理员）：按账号 / 对象类型 / 日期筛选，并给每条记录配上「对象名称」，前端拼成一句话显示。"""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AiReport, AuditLog, GlossaryTerm, InspectionTemplate, Overtime, Task, Team, User, Worker
from ..schemas import AuditOut
from ..security import require_admin

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditItem(AuditOut):
    user_name: str | None
    label: str | None  # 对象的可读名称：任务内容、人名、日期……


class AuditPage(BaseModel):
    items: list[AuditItem]
    total: int


class AuditUser(BaseModel):
    user_id: int | None  # None = 系统自动
    name: str
    username: str | None
    count: int


def _short(s: str | None, n: int = 40) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def _labels(db: Session, rows: list[AuditLog], lang: str) -> dict[int, str]:
    """批量查出每条记录对应对象的名称（对象已删除时尽量从记录里取）。"""
    want: dict[str, set] = {}
    for r in rows:
        want.setdefault(r.entity, set()).add(r.entity_id)

    def ids(entity):
        return [int(x) for x in want.get(entity, ()) if str(x).isdigit()]

    names: dict[tuple[str, str], str] = {}
    for t in db.scalars(select(Task).where(Task.id.in_(ids("task")))):
        text = getattr(t, f"content_{lang}") or getattr(t, f"content_{t.source_lang}") or ""
        names[("task", str(t.id))] = _short(text)
    for u in db.scalars(select(User).where(User.id.in_(ids("user")))):
        names[("user", str(u.id))] = f"{u.full_name}（{u.username}）" if u.full_name != u.username else u.username
    workers = dict(db.execute(select(Worker.id, Worker.name)).all()) if want.keys() & {"worker", "attendance", "overtime"} else {}
    for i in ids("worker"):
        if i in workers:
            names[("worker", str(i))] = workers[i]
    for t in db.scalars(select(Team).where(Team.id.in_(ids("team")))):
        names[("team", str(t.id))] = getattr(t, f"name_{lang}")
    for g in db.scalars(select(GlossaryTerm).where(GlossaryTerm.id.in_(ids("glossary")))):
        names[("glossary", str(g.id))] = f"{g.zh} / {g.sr} / {g.en}"
    for i in db.scalars(select(InspectionTemplate).where(InspectionTemplate.id.in_(ids("inspection")))):
        names[("inspection", str(i.id))] = i.name
    for a in db.scalars(select(AiReport).where(AiReport.id.in_(ids("ai_report")))):
        names[("ai_report", str(a.id))] = f"{a.start} ~ {a.end}"
    team_names = {t.id: getattr(t, f"name_{lang}") for t in db.scalars(select(Team))} if "overtime" in want else {}
    for o in db.scalars(select(Overtime).where(Overtime.id.in_(ids("overtime")))):
        who = workers.get(o.worker_id) if o.worker_id else team_names.get(o.team_id)
        names[("overtime", str(o.id))] = f"{who} {o.day}"
    for eid in want.get("attendance", ()):  # "员工id:日期"
        parts = str(eid).split(":")
        if len(parts) == 2 and parts[0].isdigit():
            names[("attendance", eid)] = f"{workers.get(int(parts[0]), '#' + parts[0])} {parts[1]}"
    return {r.id: names.get((r.entity, r.entity_id)) for r in rows}


@router.get("", response_model=AuditPage)
def list_audit(
    user_id: int | None = Query(default=None, description="-1 = 系统自动"),
    entity: str | None = None,
    entity_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    lang: str = Query(default="zh", pattern="^(zh|sr|en)$"),
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(AuditLog)
    if user_id == -1:
        q = q.where(AuditLog.user_id.is_(None))
    elif user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
    if entity:
        q = q.where(AuditLog.entity == entity)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    tz = get_settings().tz
    if date_from:
        q = q.where(AuditLog.at >= datetime.combine(date_from, time(0), tz))
    if date_to:
        q = q.where(AuditLog.at < datetime.combine(date_to + timedelta(days=1), time(0), tz))
    # 登录记录太多，只有专门筛「账号」类型时才显示；自动翻译只在筛「系统自动」时显示
    if entity != "user":
        q = q.where(AuditLog.action != "login")
    if user_id != -1:
        q = q.where(AuditLog.action != "translate")
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = list(db.scalars(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset)))
    names = dict(db.execute(select(User.id, User.full_name)).all())
    labels = _labels(db, rows, lang)
    return AuditPage(total=total, items=[
        AuditItem(**AuditOut.model_validate(r).model_dump(), user_name=names.get(r.user_id), label=labels.get(r.id))
        for r in rows])


@router.get("/users", response_model=list[AuditUser])
def audit_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """左侧下拉：每个账号有多少条操作记录（不含登录）。"""
    counts = dict(db.execute(select(AuditLog.user_id, func.count()).where(AuditLog.action != "login")
                             .group_by(AuditLog.user_id)).all())
    out = [AuditUser(user_id=None, name="system", username=None, count=counts.get(None, 0))]
    for u in db.scalars(select(User).order_by(User.role, User.username)):
        out.append(AuditUser(user_id=u.id, name=u.full_name, username=u.username, count=counts.get(u.id, 0)))
    return out
