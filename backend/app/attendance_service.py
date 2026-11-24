"""出勤计算：默认按排班推算（班组当天上班 → 组员出勤），再叠加导入 / 手工修改的例外记录。"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attendance, Worker
from .schedule_service import load_schedule
from .shifts import OFF, Schedule, parse_hours
from .worker_history import Entry, Timelines

STATUSES = ("present", "leave", "sick", "absent", "off")


@dataclass
class DayAttendance:
    status: str | None  # None：员工没有班组，无法推算
    shift_kind: str | None  # day / middle / night；没上班为 None
    team_id: int | None
    source: str  # default / import / manual
    note: str = ""
    hours: str | None = None  # 按排班有自定义上班时间时，例如 "07:00-12:00,14:00-17:00"


def default_for(sched: Schedule, entry: Entry, d: date) -> DayAttendance:
    """按当天有效的班组 / 个人循环推算默认出勤。"""
    if entry.team_id is None and entry.cycle is None:
        return DayAttendance(None, None, None, "default")
    raw = sched.worker_entry(sched.team(entry.team_id), entry.cycle, d)
    kind = sched.entry_kind(raw)
    if kind == OFF:
        return DayAttendance("off", None, entry.team_id, "default")
    return DayAttendance("present", kind, entry.team_id, "default", hours=raw if parse_hours(raw) else None)


def effective(db: Session, workers: list[Worker], start: date, end: date,
              sched: Schedule | None = None) -> dict[int, dict[date, DayAttendance]]:
    """返回 {worker_id: {日期: 出勤}}。员工当天属于哪个班组、跟谁排班，按变更记录（worker_schedules）算。"""
    sched = sched or load_schedule(db)
    tl = Timelines(db, workers)
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
            entry = tl.on(w.id, d)
            base = default_for(sched, entry, d)
            a = overrides.get((w.id, d))
            if a is not None:
                kind = a.shift_kind
                if a.status == "present" and not kind:
                    if a.team_id and a.team_id != entry.team_id:
                        # 去顶别的班组、没指定班次 → 按被顶班组当天的班次
                        cover = sched.team(a.team_id)
                        k = sched.shift_of(cover, d) if cover else None
                        kind = k if k and k != OFF else None
                    else:
                        kind = base.shift_kind
                # 手工改过 / 导入的：班次没变的话保留自定义上班时间
                hours = base.hours if a.status == "present" and kind == base.shift_kind else None
                row[d] = DayAttendance(a.status, kind if a.status == "present" else None,
                                       a.team_id or entry.team_id, a.source, a.note, hours)
            else:
                row[d] = base
            d += timedelta(days=1)
        out[w.id] = row
    return out


def scheduled_counts(db: Session, workers: list[Worker], start: date, end: date,
                     sched: Schedule | None = None) -> dict[int, int]:
    """每人在这段时间里按排班（不含请假、调班等例外）应上的班次数。"""
    sched = sched or load_schedule(db)
    tl = Timelines(db, workers)
    out = {}
    for w in workers:
        n, d = 0, start
        while d <= end:
            if default_for(sched, tl.on(w.id, d), d).status == "present":
                n += 1
            d += timedelta(days=1)
        out[w.id] = n
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
