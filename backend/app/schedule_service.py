"""从数据库读取配置，构造 shifts.Schedule。"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Holiday, ShiftConfig, Team
from .schemas import ShiftSlot
from .shifts import Schedule, TeamInfo


def load_schedule(db: Session) -> Schedule:
    cfg = db.get(ShiftConfig, 1)
    teams = db.scalars(select(Team).order_by(Team.sort_order)).all()
    holidays = frozenset(db.scalars(select(Holiday.day)).all())
    return Schedule(
        base_date=cfg.base_date,
        teams=tuple(TeamInfo(t.id, t.kind, t.cycle_offset) for t in teams),
        day_start=cfg.day_start,
        middle_start=cfg.middle_start,
        night_start=cfg.night_start,
        holidays=holidays,
    )


def local_now() -> datetime:
    """工厂所在时区的当前时间（naive，便于与班次时间比较）。"""
    return datetime.now(get_settings().tz).replace(tzinfo=None)


def slot(sched: Schedule, d: date, kind: str) -> ShiftSlot:
    tz = get_settings().tz
    start, end = sched.shift_window(d, kind)
    return ShiftSlot(
        shift_date=d,
        kind=kind,
        start=start.replace(tzinfo=tz),
        end=end.replace(tzinfo=tz),
        team_ids=[t.id for t in sched.teams_on(d, kind)],
    )
