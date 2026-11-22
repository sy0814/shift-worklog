"""定期巡查：计算下一次触发时间和派给哪个班组（纯函数，便于测试）。

时间都是工厂本地时间（naive datetime）。

周期类型 kind：
  daily    每隔 every_n 天（从 start_date 起算），在 at_time 触发
  weekly   每周 weekdays（0=周一 … 6=周日）的 at_time
  monthly  每月 month_days（1~31；超过当月天数按当月最后一天）的 at_time
  shift    在班次开始时触发：shift_kinds 里的班次，每隔 every_n 个（从 start_date 起数）
           —— 派给固定班组时，只数这个班组自己上的班；派给在班班组时，数全厂的这些班次

派给谁 assign：
  on_duty  触发时正在上班的倒班班组
  fixed    固定班组 team_id；如果它当时在休息，任务归到它的下一个班次
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .shifts import ORDER, Schedule, TeamInfo

MAX_SEARCH_DAYS = 800


@dataclass
class Rule:
    kind: str  # daily / weekly / monthly / shift
    at_time: time = time(8, 0)
    every_n: int = 1
    weekdays: list[int] = field(default_factory=list)
    month_days: list[int] = field(default_factory=list)
    shift_kinds: list[str] = field(default_factory=list)
    start_date: date = date(2026, 1, 1)
    assign: str = "on_duty"  # on_duty / fixed
    team_id: int | None = None


def _team(sched: Schedule, team_id: int | None) -> TeamInfo | None:
    return next((t for t in sched.teams if t.id == team_id), None)


def _shift_start(sched: Schedule, d: date, kind: str) -> datetime:
    return sched.shift_window(d, kind)[0]


def _shift_slots(sched: Schedule, rule: Rule, after: datetime):
    """按时间顺序产生 (开始时间, 日期, 班次)，只包含符合规则的班次（不考虑 every_n）。"""
    team = _team(sched, rule.team_id) if rule.assign == "fixed" else None
    d = rule.start_date
    kinds = [k for k in ORDER if k in rule.shift_kinds]
    while d <= after.date() + timedelta(days=MAX_SEARCH_DAYS):
        for k in kinds:
            if team is not None and not sched.is_on(team, d, k):
                continue
            yield _shift_start(sched, d, k), d, k
        d += timedelta(days=1)


def next_occurrence(rule: Rule, after: datetime, sched: Schedule) -> datetime | None:
    """严格晚于 after 的下一次触发时间；规则无效时返回 None。"""
    if rule.kind == "shift":
        if not rule.shift_kinds or rule.every_n < 1:
            return None
        if rule.assign == "fixed" and _team(sched, rule.team_id) is None:
            return None
        for i, (start, _d, _k) in enumerate(_shift_slots(sched, rule, after)):
            if start > after and i % rule.every_n == 0:
                return start
        return None

    d = max(after.date(), rule.start_date)
    for _ in range(MAX_SEARCH_DAYS):
        cand = datetime.combine(d, rule.at_time)
        if cand > after and _matches_day(rule, d):
            return cand
        d += timedelta(days=1)
    return None


def _matches_day(rule: Rule, d: date) -> bool:
    if d < rule.start_date:
        return False
    if rule.kind == "daily":
        return rule.every_n >= 1 and (d - rule.start_date).days % rule.every_n == 0
    if rule.kind == "weekly":
        return d.weekday() in rule.weekdays
    if rule.kind == "monthly":
        last = calendar.monthrange(d.year, d.month)[1]
        return any(min(md, last) == d.day for md in rule.month_days)
    return False


def upcoming(rule: Rule, after: datetime, sched: Schedule, count: int = 5) -> list[datetime]:
    out, cur = [], after
    for _ in range(count):
        nxt = next_occurrence(rule, cur, sched)
        if nxt is None:
            break
        out.append(nxt)
        cur = nxt
    return out


def assignment(rule: Rule, occ: datetime, sched: Schedule) -> tuple[TeamInfo | None, date, str]:
    """触发时刻 occ 的任务派给哪个班组、归属哪个班次。"""
    d, k = sched.shift_at(occ)
    if rule.assign == "fixed":
        team = _team(sched, rule.team_id)
        if team is None:
            return None, d, k
        rd, rk = sched.receiving_slot(team, occ)
        return team, rd, rk
    return sched.rotating_team_on(d, k), d, k
