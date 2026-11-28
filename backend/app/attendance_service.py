"""出勤计算：默认按排班推算（班组当天上班 → 组员出勤），再叠加导入 / 手工修改的例外记录。"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attendance, Worker
from .schedule_service import load_schedule
from .shifts import OFF, Schedule, note, parse_hours
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
    code: str | None = None  # 出勤月表里的原始写法（AL、SL、BT……）


def default_for(sched: Schedule, entry: Entry, d: date, trace: list | None = None) -> DayAttendance:
    """按当天有效的班组 / 个人循环推算默认出勤。"""
    note(trace, "membership", team_id=entry.team_id, since=entry.effective_from, personal=entry.cycle is not None)
    if entry.team_id is None and entry.cycle is None:
        return DayAttendance(None, None, None, "default")
    raw = sched.worker_entry(sched.team(entry.team_id), entry.cycle, d, trace)
    kind = sched.entry_kind_traced(raw, trace)
    if kind == OFF:
        return DayAttendance("off", None, entry.team_id, "default")
    return DayAttendance("present", kind, entry.team_id, "default", hours=raw if parse_hours(raw) else None)


def resolve(sched: Schedule, entry: Entry, a: Attendance | None, d: date,
            trace: list | None = None) -> DayAttendance:
    """某人某天的出勤：先按排班推算（default_for），有例外记录（导入 / 手工改）就以例外为准。
    出勤表、首页在岗、导出、AI 统计和「为什么？」都走这里（trace 记下每一步依据）。"""
    base = default_for(sched, entry, d, trace)
    if a is None:
        return base
    note(trace, "attendance", status=a.status, shift_kind=a.shift_kind, team_id=a.team_id, source=a.source,
         note=a.note, by=a.updated_by, at=a.updated_at)
    kind = a.shift_kind
    if a.status == "present" and not kind:
        if a.team_id and a.team_id != entry.team_id:
            # 去顶别的班组、没指定班次 → 跟着被顶班组走：它当天上什么班就上什么班，它休息他也休息（用户 2026-11-28 定的）
            cover = sched.team(a.team_id)
            k = sched.shift_of(cover, d) if cover else None
            kind = k if k and k != OFF else None
            note(trace, "cover", team_id=a.team_id, kind=kind)
            if kind is None:
                return DayAttendance("off", None, a.team_id, a.source, a.note)
        else:
            kind = base.shift_kind
    # 手工改过 / 导入的：班次没变的话保留自定义上班时间
    hours = base.hours if a.status == "present" and kind == base.shift_kind else None
    if base.hours and a.status == "present" and hours is None:
        note(trace, "hours_dropped", hours=base.hours)
    return DayAttendance(a.status, kind if a.status == "present" else None,
                         a.team_id or entry.team_id, a.source, a.note, hours, getattr(a, "code", None))


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
            row[d] = resolve(sched, tl.on(w.id, d), overrides.get((w.id, d)), d)
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


# ---------------- 工厂出勤月表（SSZM）----------------
# 一行一个人（Sap No. = 工号），一列一天：1 / 2 / 3 = 白 / 中 / 夜（夜班记在下班那天），/ = 休息，
# 其余是缩写（表头说明里列着）。对应到系统的状态（用户 2026-11-27 定的），原来的缩写存进 code 和备注，出勤页原样显示。
SHEET_CODES = {
    "AL": "leave", "UL": "leave", "BT": "leave",  # 年假、无薪假、出差（不在现场）；PL…（各种带薪假）见 sheet_cell
    "SL": "sick", "SLI": "sick", "SLP": "sick",
    "PH": "off", "RH": "off", "SH": "off",  # 法定假、宗教节日（Slava）、用攒的工时调休
    "EH": "present",  # 攒工时（来上班了）
    "RW": "absent",  # 停工
}
SHEET_SHIFTS = {"1": "day", "2": "middle", "3": "night"}
_SHEET_HOURS = __import__("re").compile(r"^([123])\s*[-–—]\s*\d{1,2}\s*H?$")
_SHEET_JUNK = " .·。,，、'\""


def sheet_cell(v) -> tuple[str, str | None, str | None] | str | None:
    """月表的一格 → (状态, 班次, 原始缩写)；空格子 → None（不改）；认不出 → "invalid"。
    「2.」「2·」「3.」这类手误按数字认。"""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip().strip(_SHEET_JUNK).upper()
    if s == "":
        return None
    if s in SHEET_SHIFTS:
        return "present", SHEET_SHIFTS[s], None
    if m := _SHEET_HOURS.match(s):  # 1-8H / 1-10H / 1-12H：只按那个班算（用户 2026-11-27：只算 8 小时，不管时长）
        return "present", SHEET_SHIFTS[m[1]], None
    if s in ("/", "\\"):
        return "off", None, None
    if s in SHEET_CODES:
        return SHEET_CODES[s], None, s
    if s.startswith("PL") and s[2:].isalpha() and len(s) <= 6:  # PLC、PLM、PLE、PLD、PLBD、PLW、PLCB……带薪假
        return "leave", None, s
    return "invalid"
