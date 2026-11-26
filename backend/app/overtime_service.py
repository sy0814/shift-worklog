"""加班：把「某人 / 整个班组」的加班记录展开到每个人，算加班时长。

整个班组的加班 = 当天（按出勤，含调班、顶班）在这个班组上这个班的每个人都加班。
加班时长 = 加班到的时间 − 班次结束时间（小时）。
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import attendance_service as att
from .config import get_settings
from .models import Overtime, Worker
from .schedule_service import load_schedule, local_hours


@dataclass
class WorkerOvertime:
    overtime_id: int
    worker_id: int
    day: date
    shift_kind: str
    end_local: datetime  # 班次结束（本地 naive）
    until_local: datetime  # 加班到（本地 naive）
    hours: float
    note: str
    whole_team: bool


def to_local(d: datetime) -> datetime:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(get_settings().tz).replace(tzinfo=None)


def expand(db: Session, start: date, end: date, workers: list[Worker] | None = None) -> list[WorkerOvertime]:
    """时间段内（按班次日）每个人的加班。workers 不传 = 所有在职员工。"""
    rows = list(db.scalars(select(Overtime).where(Overtime.day >= start, Overtime.day <= end).order_by(Overtime.day)))
    if not rows:
        return []
    if workers is None:
        workers = list(db.scalars(select(Worker).where(Worker.is_active.is_(True))))
    by_id = {w.id: w for w in workers}
    eff = att.effective(db, workers, start, end)
    sched = load_schedule(db)
    best: dict[tuple, WorkerOvertime] = {}  # 同一人同一班次有多条（个人 + 全班）时，取加班到最晚的那条
    for o in rows:
        shift_end = sched.shift_window(o.day, o.shift_kind)[1]
        until = to_local(o.until)
        hours = round(max(0.0, local_hours(shift_end, until)), 2)  # 真实时长（夏令时那一夜和钟面差不一样）
        if o.worker_id is not None:
            ids = [o.worker_id] if o.worker_id in by_id else []
        else:
            ids = [w.id for w in workers
                   if (a := eff[w.id][o.day]).status == "present" and a.shift_kind == o.shift_kind
                   and (a.team_id or w.team_id) == o.team_id]
        for wid in ids:
            # 有自定义上班时间的人（例如 07:00-12:00,14:00-17:00）：加班从他实际下班的时间算
            a = eff[wid][o.day] if wid in eff else None
            end_w = shift_end
            if a is not None and a.hours and a.shift_kind == o.shift_kind:
                end_w = sched.entry_hours(a.hours, o.day)[-1][1]
            hours_w = round(max(0.0, local_hours(end_w, until)), 2)
            key = (wid, o.day, o.shift_kind)
            if key not in best or best[key].until_local < until:
                best[key] = WorkerOvertime(o.id, wid, o.day, o.shift_kind, end_w, until, hours_w, o.note,
                                           o.worker_id is None)
    return list(best.values())


def hours_by_worker(db: Session, start: date, end: date, workers: list[Worker]) -> dict[int, float]:
    total: dict[int, float] = {}
    for x in expand(db, start, end, workers):
        total[x.worker_id] = round(total.get(x.worker_id, 0) + x.hours, 2)
    return total
