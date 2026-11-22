"""出勤计算：默认按排班推算（班组当天上班 → 组员出勤），再叠加导入 / 手工修改的例外记录。"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attendance, Worker
from .schedule_service import load_schedule
from .shifts import OFF, Schedule

STATUSES = ("present", "leave", "sick", "absent", "off")


@dataclass
class DayAttendance:
    status: str | None  # None：员工没有班组，无法推算
    shift_kind: str | None  # day / middle / night；没上班为 None
    team_id: int | None
    source: str  # default / import / manual
    note: str = ""


def default_for(sched: Schedule, worker: Worker, d: date) -> DayAttendance:
    if worker.team_id is None:
        return DayAttendance(None, None, None, "default")
    team = next((t for t in sched.teams if t.id == worker.team_id), None)
    if team is None:
        return DayAttendance(None, None, None, "default")
    kind = sched.shift_of(team, d)
    if kind == OFF:
        return DayAttendance("off", None, worker.team_id, "default")
    return DayAttendance("present", kind, worker.team_id, "default")


def effective(db: Session, workers: list[Worker], start: date, end: date) -> dict[int, dict[date, DayAttendance]]:
    """返回 {worker_id: {日期: 出勤}}。"""
    sched = load_schedule(db)
    ids = [w.id for w in workers]
    overrides = {}
    if ids:
        for a in db.scalars(select(Attendance).where(Attendance.worker_id.in_(ids), Attendance.day >= start,
                                                     Attendance.day <= end)):
            overrides[(a.worker_id, a.day)] = a
    out: dict[int, dict[date, DayAttendance]] = {}
    for w in workers:
        row = {}
        d = start
        while d <= end:
            base = default_for(sched, w, d)
            a = overrides.get((w.id, d))
            if a is not None:
                kind = a.shift_kind or (base.shift_kind if a.status == "present" else None)
                row[d] = DayAttendance(a.status, kind if a.status == "present" else None,
                                       a.team_id or w.team_id, a.source, a.note)
            else:
                row[d] = base
            d += timedelta(days=1)
        out[w.id] = row
    return out


# 导入时接受的状态写法（中 / 塞 / 英，含常见简写）
STATUS_ALIASES = {
    "present": ["出勤", "上班", "在岗", "√", "✓", "p", "present", "prisutan", "prisutna", "rad", "radio"],
    "leave": ["请假", "事假", "年假", "休假", "l", "leave", "odsustvo", "godišnji", "godisnji", "go"],
    "sick": ["病假", "s", "sick", "bolovanje", "bol"],
    "absent": ["缺勤", "旷工", "a", "absent", "izostanak", "neopravdano"],
    "off": ["休息", "休", "轮休", "o", "off", "slobodan", "slobodno"],
}
_ALIAS = {a.lower(): k for k, v in STATUS_ALIASES.items() for a in v}

SHIFT_ALIASES = {
    "day": ["白班", "白", "day", "d", "prva", "i", "1"],
    "middle": ["中班", "中", "middle", "m", "druga", "ii", "2"],
    "night": ["夜班", "夜", "night", "n", "treća", "treca", "iii", "3"],
}
_SHIFT = {a.lower(): k for k, v in SHIFT_ALIASES.items() for a in v}


def parse_status(v) -> str | None:
    if v is None:
        return None
    return _ALIAS.get(str(v).strip().lower())


def parse_shift(v) -> str | None:
    if v is None or str(v).strip() == "":
        return None
    return _SHIFT.get(str(v).strip().lower(), "invalid")
