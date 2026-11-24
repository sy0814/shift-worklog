"""加班：给某人（可多选）或整个班组设置某个班次加班到几点。

权限：管理员任何人 / 班组；班长：本班组的人、本班组整体，以及当天在本班组上班（来支援）的人。
"""

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import attendance_service as att
from .. import permissions
from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import Overtime, Team, User, Worker, utcnow
from ..overtime_service import expand, to_local
from ..schedule_service import load_schedule
from ..schemas import UTCDateTime
from ..security import get_current_user

router = APIRouter(prefix="/api/overtime", tags=["overtime"])
MAX_HOURS = 16


class OvertimeIn(BaseModel):
    day: date  # 班次日（夜班归属开始那天）
    shift_kind: str | None = Field(default=None, pattern="^(day|middle|night)$")  # 不填 = 按当天出勤 / 排班
    team_id: int | None = None  # 整个班组
    worker_ids: list[int] = Field(default_factory=list, max_length=200)  # 或者这几个人
    until: time  # 加班到几点（本地时间；班次结束之后最近的这个时刻）
    note: str = Field(default="", max_length=200)


class OvertimeOut(BaseModel):
    id: int
    day: date
    shift_kind: str
    team_id: int | None
    worker_id: int | None
    worker_name: str | None
    until: UTCDateTime
    hours: float
    people: int  # 整个班组时，展开后有几个人
    note: str
    created_by_name: str


def _until(sched, d: date, kind: str, hhmm: time) -> tuple[datetime, float]:
    end = sched.shift_window(d, kind)[1]
    until = datetime.combine(end.date(), hhmm)
    if until <= end:
        until += timedelta(days=1)
    hours = (until - end).total_seconds() / 3600
    if hours > MAX_HOURS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"overtime must end within {MAX_HOURS} h after the shift")
    return until, hours


def _out(db: Session, rows: list[Overtime]) -> list[OvertimeOut]:
    if not rows:
        return []
    names = dict(db.execute(select(User.id, User.full_name)).all())
    wnames = dict(db.execute(select(Worker.id, Worker.name)).all())
    start, end = min(r.day for r in rows), max(r.day for r in rows)
    counts: dict[int, int] = {}
    for x in expand(db, start, end):
        counts[x.overtime_id] = counts.get(x.overtime_id, 0) + 1
    sched = load_schedule(db)
    out = []
    for r in rows:
        shift_end = sched.shift_window(r.day, r.shift_kind)[1]
        out.append(OvertimeOut(
            id=r.id, day=r.day, shift_kind=r.shift_kind, team_id=r.team_id, worker_id=r.worker_id,
            worker_name=wnames.get(r.worker_id), until=r.until,
            hours=round(max(0.0, (to_local(r.until) - shift_end).total_seconds() / 3600), 2),
            people=counts.get(r.id, 0) if r.team_id else 1, note=r.note,
            created_by_name=names.get(r.created_by, "")))
    return out


@router.get("", response_model=list[OvertimeOut])
def list_overtime(start: date, end: date, team_id: int | None = None, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    if end < start or (end - start).days > 92:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be 0..92 days")
    q = select(Overtime).where(Overtime.day >= start, Overtime.day <= end)
    rows = list(db.scalars(q.order_by(Overtime.day.desc(), Overtime.id.desc())))
    if team_id:
        ws = {w.id: w.team_id for w in db.scalars(select(Worker))}
        rows = [r for r in rows if r.team_id == team_id or ws.get(r.worker_id) == team_id]
    return _out(db, rows)


@router.post("", response_model=list[OvertimeOut], status_code=201)
def add_overtime(body: OvertimeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if (body.team_id is None) == (not body.worker_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "give either team_id or worker_ids")
    sched = load_schedule(db)
    who = permissions.who(db, user)
    permissions.require(who.has("overtime.edit"))
    tz = get_settings().tz
    created = []
    if body.team_id is not None:
        team = next((t for t in sched.teams if t.id == body.team_id), None)
        if team is None or db.get(Team, body.team_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
        if not who.team_ok("overtime.edit", body.team_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team")
        kind = body.shift_kind or sched.shift_of(team, body.day)
        if kind not in ("day", "middle", "night"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "team is off that day; choose a shift")
        until, _h = _until(sched, body.day, kind, body.until)
        created.append(Overtime(day=body.day, shift_kind=kind, team_id=body.team_id,
                                until=until.replace(tzinfo=tz).astimezone(timezone.utc), note=body.note.strip(), created_by=user.id))
    else:
        workers = list(db.scalars(select(Worker).where(Worker.id.in_(body.worker_ids))))
        if len(workers) != len(set(body.worker_ids)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown worker")
        eff = att.effective(db, workers, body.day, body.day)
        for w in workers:
            a = eff[w.id][body.day]
            if not (who.team_ok("overtime.edit", w.team_id) or who.team_ok("overtime.edit", a.team_id)):
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"{w.name} is not in your team")
            kind = body.shift_kind or (a.shift_kind if a.status == "present" else None)
            if kind is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{w.name} is not on duty that day; choose a shift")
            until, _h = _until(sched, body.day, kind, body.until)
            created.append(Overtime(day=body.day, shift_kind=kind, worker_id=w.id,
                                    until=until.replace(tzinfo=tz).astimezone(timezone.utc), note=body.note.strip(), created_by=user.id))
    for o in created:
        o.created_at = utcnow()
        db.add(o)
        db.flush()
        audit.log(db, user_id=user.id, action="create", entity="overtime", entity_id=o.id,
                  new={"day": str(o.day), "shift": o.shift_kind, "team_id": o.team_id, "worker_id": o.worker_id,
                       "until": o.until.isoformat(), "note": o.note})
    db.commit()
    return _out(db, created)


@router.delete("/{oid}", status_code=204)
def delete_overtime(oid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    o = db.get(Overtime, oid)
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    who = permissions.who(db, user)
    w = db.get(Worker, o.worker_id) if o.worker_id else None
    if not who.team_ok("overtime.edit", o.team_id or (w.team_id if w else None)) and o.created_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team")
    audit.log(db, user_id=user.id, action="delete", entity="overtime", entity_id=o.id,
              old={"day": str(o.day), "shift": o.shift_kind, "team_id": o.team_id, "worker_id": o.worker_id,
                   "until": o.until.isoformat()})
    db.delete(o)
    db.commit()


class PersonOvertime(BaseModel):
    overtime_id: int
    worker_id: int
    day: date
    shift_kind: str
    until: datetime  # 本地时间
    hours: float
    whole_team: bool
    note: str


@router.get("/people", response_model=list[PersonOvertime])
def people_overtime(start: date, end: date, team_id: int | None = None, db: Session = Depends(get_db),
                    _: User = Depends(get_current_user)):
    """展开到每个人的加班（整个班组的加班会列出当天上这个班的每个人），出勤表用。"""
    if end < start or (end - start).days > 92:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be 0..92 days")
    tz = get_settings().tz
    out = [PersonOvertime(overtime_id=x.overtime_id, worker_id=x.worker_id, day=x.day, shift_kind=x.shift_kind,
                          until=x.until_local.replace(tzinfo=tz), hours=x.hours, whole_team=x.whole_team, note=x.note)
           for x in expand(db, start, end)]
    if team_id:
        ws = {w.id: w.team_id for w in db.scalars(select(Worker))}
        # 本班组的人，以及整个本班组加班里来支援的人
        team_ot = {o.id for o in db.scalars(select(Overtime).where(Overtime.team_id == team_id))}
        out = [p for p in out if ws.get(p.worker_id) == team_id or p.overtime_id in team_ot]
    return out
