"""班组、排班、节假日。"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Holiday, ShiftConfig, Team, User
from ..schedule_service import load_schedule, local_now, slot
from ..schemas import (
    CalendarDay,
    HolidayIO,
    ShiftConfigIn,
    ShiftConfigOut,
    ShiftNow,
    TeamOut,
)
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
                               shifts={t.id: sched.shift_of(t, d) for t in sched.teams}))
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
        h = Holiday(day=day, name=body.name)
        db.add(h)
        audit.log(db, user_id=admin.id, action="create", entity="holiday", entity_id=day,
                  new=body.name)
    else:
        audit.log_changes(db, h, {"name": body.name}, user_id=admin.id,
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
