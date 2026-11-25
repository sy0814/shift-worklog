"""从数据库读取配置，构造 shifts.Schedule。"""

import dataclasses
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Holiday, ShiftConfig, Team, TeamShiftOverride
from .schemas import ShiftSlot
from .shifts import ALL, ORDER, Cycle, Schedule, TeamInfo


def load_schedule(db: Session) -> Schedule:
    base = _load_base(db)
    if not any(not t.is_main for t in base.teams):
        return base
    own = base  # 算成员出勤时用不带「成员带出来的班次」的排班，避免互相依赖
    return dataclasses.replace(base, member_fn=lambda d: member_days(db, own, d), _member_cache={})


def member_days(db: Session, own: Schedule, d: date) -> dict:
    """非主班组的成员被单独安排上班的日子：{日期: {班组 id: 班次}}（一次算 d 前 3 天到后 31 天）。
    同一天成员上不同的班时，取人最多的那个班。"""
    from . import attendance_service
    from .models import Attendance, Worker, WorkerSchedule

    start, end = d - timedelta(days=3), d + timedelta(days=31)
    days = {start + timedelta(days=i): {} for i in range((end - start).days + 1)}
    nonmain = [t.id for t in own.teams if not t.is_main]
    ids = set(db.scalars(select(Worker.id).where(Worker.team_id.in_(nonmain))))
    ids |= set(db.scalars(select(WorkerSchedule.worker_id).where(WorkerSchedule.team_id.in_(nonmain))))
    ids |= set(db.scalars(select(Attendance.worker_id).where(Attendance.team_id.in_(nonmain),
                                                             Attendance.day >= start, Attendance.day <= end)))
    if not ids:
        return days
    workers = list(db.scalars(select(Worker).where(Worker.id.in_(ids), Worker.is_active.is_(True))))
    for day, shifts in vote_member_shifts(attendance_service.effective(db, workers, start, end, own).values(),
                                          set(nonmain)).items():
        days[day].update(shifts)
    return days


def vote_member_shifts(rows, nonmain: set) -> dict:
    """（纯函数）成员出勤 → {日期: {非主班组 id: 班次}}：有成员出勤上某个班，班组就算上这个班；
    同一天成员上不同的班时，取人最多的那个（一样多取先上的）。rows = 每人 {日期: DayAttendance}。"""
    votes: dict = {}
    for row in rows:
        for day, a in row.items():
            if a.status == "present" and a.shift_kind and a.team_id in nonmain:
                votes.setdefault((day, a.team_id), Counter())[a.shift_kind] += 1
    out: dict = {}
    for (day, tid), c in votes.items():
        out.setdefault(day, {})[tid] = max(c, key=lambda k: (c[k], -ORDER.index(k)))
    return out


def _load_base(db: Session) -> Schedule:
    cfg = db.get(ShiftConfig, 1)
    teams = db.scalars(select(Team).order_by(Team.sort_order)).all()
    rows = db.execute(select(Holiday.day, Holiday.kind)).all()
    holidays = frozenset(d for d, k in rows if k != "workday")
    workdays = frozenset(d for d, k in rows if k == "workday")
    return Schedule(
        teams=tuple(team_info(t) for t in teams),
        day_start=cfg.day_start,
        middle_start=cfg.middle_start,
        night_start=cfg.night_start,
        holidays=holidays,
        extra_workdays=workdays,
        overrides={(o.team_id, o.day): o.hours or o.shift_kind  # 自定义时间段优先
                   for o in db.execute(select(TeamShiftOverride.team_id, TeamShiftOverride.day,
                                              TeamShiftOverride.shift_kind, TeamShiftOverride.hours)).all()},
    )


def team_info(t: Team) -> TeamInfo:
    cycle = Cycle(tuple(t.pattern), t.cycle_start, bool(t.holiday_off)) \
        if t.kind == "cycle" and t.pattern and t.cycle_start else None
    return TeamInfo(t.id, cycle, bool(t.is_main), t.active_from, t.active_to, t.department_id)


def local_now() -> datetime:
    """工厂所在时区的当前时间（naive，便于与班次时间比较）。"""
    return datetime.now(get_settings().tz).replace(tzinfo=None)


def slot(sched: Schedule, d: date, kind: str, dept=ALL) -> ShiftSlot:
    tz = get_settings().tz
    start, end = sched.shift_window(d, kind)
    return ShiftSlot(
        shift_date=d,
        kind=kind,
        start=start.replace(tzinfo=tz),
        end=end.replace(tzinfo=tz),
        team_ids=[t.id for t in sched.teams_on(d, kind, dept)],
    )
