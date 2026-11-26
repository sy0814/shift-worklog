"""自定义上班时间（例如 07:00-12:00,14:00-17:00）的「实际时间」判断，首页在岗和能分配任务的人共用。

班次分组按「和哪个班重叠最多」算（shifts.Schedule.entry_kind）；这里管的是实际时间带来的几件事：
  - 在这个班但现在不在时间段里（午休、还没到点）→ 首页「休息中」，下一段几点开始
  - 时间段跨过了班次分界（例如白班组 14:00-17:00，16:00 已经是中班）→ 现在在上班，也算在岗
  - 算在别的班，但有一段落在这个班次里 → 这个班次也列出来，写明到几点
出勤要传前一天、当天、第二天三天的（夜班记在下班那天：第二天的出勤可能当天晚上就开始）。
"""

from datetime import datetime, timedelta


def in_hours(sched, hours: str, d, now: datetime) -> bool:
    """now 在不在 d 这天的时间段里。"""
    return any(a <= now < b for a, b in sched.entry_hours(hours, d))


def next_start(sched, hours: str, d, now: datetime) -> datetime | None:
    """now 之后最近一段的开始时间（本地 naive）；今天的时间段都结束了返回 None。"""
    starts = [a for a, _b in sched.entry_hours(hours, d) if a > now]
    return min(starts) if starts else None


def _days(d):
    return (d, d + timedelta(days=1), d - timedelta(days=1))


def working_now(sched, row: dict, d, now: datetime):
    """有自定义上班时间、而且现在正在时间段里的那一天的出勤；没有返回 None。row = {日期: 出勤}。"""
    for day in _days(d):
        a = row.get(day)
        if a is not None and a.status == "present" and a.hours and in_hours(sched, a.hours, day, now):
            return a
    return None


def overlap(sched, row: dict, d, k: str, start: datetime, end: datetime, now: datetime | None):
    """有自定义上班时间、算在别的班（不是 k），但时间段有一部分落在班次 [start, end) 里的那一天的出勤。
    now 给了（当前班次）就只看还没结束的部分。返回 (出勤, 从, 到) 或 None。"""
    for day in _days(d):
        a = row.get(day)
        if a is None or a.status != "present" or not a.hours or a.shift_kind == k:
            continue
        parts = [(max(x, start, now or start), min(y, end)) for x, y in sched.entry_hours(a.hours, day)]
        parts = [(x, y) for x, y in parts if x < y]
        if parts:
            return a, min(x for x, _ in parts), max(y for _, y in parts)
    return None
