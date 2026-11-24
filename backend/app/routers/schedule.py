"""班组、排班、节假日。"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Holiday, ShiftConfig, Team, TeamShiftOverride, User, utcnow
from ..schedule_service import load_schedule, local_now, slot
from ..schemas import (
    CalendarDay,
    HolidayIO,
    ShiftConfigIn,
    ShiftConfigOut,
    ShiftNow,
    TeamOut,
)
from pydantic import BaseModel, Field

from ..security import get_current_user, require_admin
from ..shifts import CYCLE

router = APIRouter(prefix="/api", tags=["schedule"])


@router.get("/teams", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(Team).order_by(Team.sort_order)).all()


@router.get("/shifts/now", response_model=ShiftNow)
def shifts_now(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    sched = load_schedule(db)
    now = local_now()
    d, k = sched.shift_at(now)
    nd, nk = sched.next_shift(d, k)
    return ShiftNow(now=now, current=slot(sched, d, k), next=slot(sched, nd, nk))


@router.get("/shifts/calendar", response_model=list[CalendarDay])
def shifts_calendar(start: date, end: date, db: Session = Depends(get_db),
                    _: User = Depends(get_current_user)):
    if end < start or (end - start).days > 92:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be 0..92 days")
    sched = load_schedule(db)
    out = []
    d = start
    while d <= end:
        out.append(CalendarDay(day=d, workday=sched.is_workday(d),
                               shifts={t.id: sched.shift_of(t, d) for t in sched.teams},
                               changed={t.id: sched.planned_shift_of(t, d) for t in sched.teams
                                        if (t.id, d) in sched.overrides}))
        d += timedelta(days=1)
    return out


@router.get("/shifts/config", response_model=ShiftConfigOut)
def get_config(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.get(ShiftConfig, 1)


@router.put("/shifts/config", response_model=ShiftConfigOut)
def put_config(body: ShiftConfigIn, db: Session = Depends(get_db),
               admin: User = Depends(require_admin)):
    if not (body.day_start < body.middle_start < body.night_start):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "shift start times must be increasing")
    rotating = {t.id: t for t in db.scalars(select(Team).where(Team.kind == "rotating"))}
    if set(body.offsets) != set(rotating):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "offsets must cover every rotating team")
    if any(not 0 <= v < len(CYCLE) for v in body.offsets.values()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "offset must be 0..7")
    # 每天必须正好一个白/中/夜/休：同一循环里两个位置属于同一班次（0,1 / 2,3 ...），
    # 4 个班组的 offset // 2 必须各不相同
    if len({v // 2 for v in body.offsets.values()}) != len(rotating):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "teams must be in different shift pairs (2 days apart)")
    cfg = db.get(ShiftConfig, 1)
    audit.log_changes(db, cfg, body.model_dump(exclude={"offsets"}),
                      user_id=admin.id, entity="shift_config", entity_id=1)
    for tid, off in body.offsets.items():
        audit.log_changes(db, rotating[tid], {"cycle_offset": off},
                          user_id=admin.id, entity="team", entity_id=tid)
    db.commit()
    return cfg


@router.get("/holidays", response_model=list[HolidayIO])
def list_holidays(year: int | None = Query(default=None), db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    q = select(Holiday).order_by(Holiday.day)
    if year:
        q = q.where(Holiday.day >= date(year, 1, 1), Holiday.day <= date(year, 12, 31))
    return db.scalars(q).all()


@router.put("/holidays/{day}", response_model=HolidayIO)
def put_holiday(day: date, body: HolidayIO, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    h = db.get(Holiday, day)
    if h is None:
        h = Holiday(day=day, name=body.name, kind=body.kind)
        db.add(h)
        audit.log(db, user_id=admin.id, action="create", entity="holiday", entity_id=day,
                  new={"name": body.name, "kind": body.kind})
    else:
        audit.log_changes(db, h, {"name": body.name, "kind": body.kind}, user_id=admin.id,
                          entity="holiday", entity_id=day)
    db.commit()
    return h


@router.delete("/holidays/{day}", status_code=204)
def delete_holiday(day: date, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    h = db.get(Holiday, day)
    if h is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    audit.log(db, user_id=admin.id, action="delete", entity="holiday", entity_id=day, old=h.name)
    db.delete(h)
    db.commit()


# ---------------- 班组整体调班 ----------------
class TeamShiftIn(BaseModel):
    team_id: int
    start: date
    end: date
    shift_kind: str = Field(pattern="^(day|middle|night|off)$")
    note: str = Field(default="", max_length=200)


class TeamShiftOut(BaseModel):
    team_id: int
    day: date
    shift_kind: str
    planned: str  # 原本按排班该上的班
    note: str


def _ts_out(sched, o: TeamShiftOverride) -> TeamShiftOut:
    team = next(t for t in sched.teams if t.id == o.team_id)
    return TeamShiftOut(team_id=o.team_id, day=o.day, shift_kind=o.shift_kind,
                        planned=sched.planned_shift_of(team, o.day), note=o.note)


def _range(start: date, end: date) -> list[date]:
    if end < start or (end - start).days > 30:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be 1..31 days")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


@router.get("/team-shifts", response_model=list[TeamShiftOut])
def list_team_shifts(start: date, end: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    sched = load_schedule(db)
    rows = db.scalars(select(TeamShiftOverride).where(TeamShiftOverride.day >= start, TeamShiftOverride.day <= end)
                      .order_by(TeamShiftOverride.day, TeamShiftOverride.team_id)).all()
    return [_ts_out(sched, o) for o in rows]


@router.put("/team-shifts", response_model=list[TeamShiftOut])
def set_team_shift(body: TeamShiftIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """某个班组在某几天整体改上某个班（或休息）。和原排班相同的日子不记录（等于恢复）。"""
    team = db.get(Team, body.team_id)
    if team is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
    sched = load_schedule(db)
    info = next(t for t in sched.teams if t.id == team.id)
    for d in _range(body.start, body.end):
        row = db.scalar(select(TeamShiftOverride).where(TeamShiftOverride.team_id == team.id,
                                                        TeamShiftOverride.day == d))
        old = row.shift_kind if row else sched.planned_shift_of(info, d)
        if body.shift_kind == sched.planned_shift_of(info, d):
            if row:
                db.delete(row)
        elif row:
            row.shift_kind, row.note = body.shift_kind, body.note.strip()
        else:
            db.add(TeamShiftOverride(team_id=team.id, day=d, shift_kind=body.shift_kind, note=body.note.strip(),
                                     created_by=admin.id, created_at=utcnow()))
        if old != body.shift_kind:
            audit.log(db, user_id=admin.id, action="update", entity="team", entity_id=team.id,
                      field="team_shift", old=f"{d} {old}", new=f"{d} {body.shift_kind}",
                      extra={"day": str(d), "note": body.note})
    db.commit()
    return list_team_shifts(body.start, body.end, db, admin)


@router.delete("/team-shifts", status_code=204)
def clear_team_shift(team_id: int, start: date, end: date, db: Session = Depends(get_db),
                     admin: User = Depends(require_admin)):
    """恢复按排班。"""
    sched = load_schedule(db)
    info = next((t for t in sched.teams if t.id == team_id), None)
    if info is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
    days = _range(start, end)
    for row in db.scalars(select(TeamShiftOverride).where(TeamShiftOverride.team_id == team_id,
                                                          TeamShiftOverride.day.in_(days))).all():
        audit.log(db, user_id=admin.id, action="update", entity="team", entity_id=team_id, field="team_shift",
                  old=f"{row.day} {row.shift_kind}", new=f"{row.day} {sched.planned_shift_of(info, row.day)}",
                  extra={"day": str(row.day), "restore": True})
        db.delete(row)
    db.commit()
