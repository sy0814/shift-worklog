"""排班推算（纯函数，不依赖数据库）。

倒班：8 天循环「白 白 中 中 夜 夜 休 休」，位置 0..7。
某日某班位置 = (起始位置 + 距基准天数) mod 8。
夜班归属开始的那一天：11-21 23:00 ~ 11-22 07:00 记为 11-21 的夜班。
常白班：周一到周五白班时段上班，周末和节假日休息。
交接顺序：夜班 → 白班 → 中班 → 夜班。
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

DAY, MIDDLE, NIGHT, OFF = "day", "middle", "night", "off"
CYCLE = (DAY, DAY, MIDDLE, MIDDLE, NIGHT, NIGHT, OFF, OFF)
ORDER = (DAY, MIDDLE, NIGHT)  # 一个「班次日」内的先后顺序


@dataclass(frozen=True)
class TeamInfo:
    id: int
    kind: str  # rotating / day
    cycle_offset: int | None = None


@dataclass(frozen=True)
class Schedule:
    base_date: date
    teams: tuple[TeamInfo, ...]
    day_start: time = time(7)
    middle_start: time = time(15)
    night_start: time = time(23)
    holidays: frozenset[date] = frozenset()

    # ---- 单个班组 ----
    def cycle_pos(self, team: TeamInfo, d: date) -> int:
        assert team.kind == "rotating" and team.cycle_offset is not None
        return (team.cycle_offset + (d - self.base_date).days) % len(CYCLE)

    def is_workday(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def shift_of(self, team: TeamInfo, d: date) -> str:
        if team.kind == "rotating":
            return CYCLE[self.cycle_pos(team, d)]
        return DAY if self.is_workday(d) else OFF

    # ---- 某天 / 某时刻 ----
    def rotating_team_on(self, d: date, kind: str) -> TeamInfo | None:
        for t in self.teams:
            if t.kind == "rotating" and self.shift_of(t, d) == kind:
                return t
        return None

    def teams_on(self, d: date, kind: str) -> list[TeamInfo]:
        """某班次日某班次在班的所有班组（白班时可能包含常白班）。"""
        return [t for t in self.teams if self.shift_of(t, d) == kind]

    def shift_at(self, dt: datetime) -> tuple[date, str]:
        """本地时间 dt 属于哪个班次日的哪个班次。"""
        d, t = dt.date(), dt.time()
        if t < self.day_start:
            return d - timedelta(days=1), NIGHT
        if t < self.middle_start:
            return d, DAY
        if t < self.night_start:
            return d, MIDDLE
        return d, NIGHT

    @staticmethod
    def next_shift(d: date, kind: str) -> tuple[date, str]:
        i = ORDER.index(kind)
        if i + 1 < len(ORDER):
            return d, ORDER[i + 1]
        return d + timedelta(days=1), ORDER[0]

    def shift_window(self, d: date, kind: str) -> tuple[datetime, datetime]:
        """班次起止（本地 naive 时间）。"""
        start_t = {DAY: self.day_start, MIDDLE: self.middle_start, NIGHT: self.night_start}[kind]
        start = datetime.combine(d, start_t)
        nd, nk = self.next_shift(d, kind)
        end_t = {DAY: self.day_start, MIDDLE: self.middle_start, NIGHT: self.night_start}[nk]
        return start, datetime.combine(nd, end_t)

    def handover_target(self, team: TeamInfo, d: date, kind: str) -> TeamInfo | None:
        """默认移交对象：倒班交给下一个班次的倒班班组；常白班交给当天中班。"""
        if team.kind == "day":
            return self.rotating_team_on(d, MIDDLE)
        nd, nk = self.next_shift(d, kind)
        return self.rotating_team_on(nd, nk)

    def next_shift_of_team(self, team: TeamInfo, after: date, kind: str) -> tuple[date, str]:
        """班组在 (after, kind) 之后的下一个上班班次（最多向后找 30 天）。"""
        d, k = self.next_shift(after, kind)
        for _ in range(30 * len(ORDER)):
            if self.shift_of(team, d) == k:
                return d, k
            d, k = self.next_shift(d, k)
        raise ValueError("no upcoming shift")

    # ---- 移交相关 ----
    @staticmethod
    def prev_shift(d: date, kind: str) -> tuple[date, str]:
        i = ORDER.index(kind)
        if i > 0:
            return d, ORDER[i - 1]
        return d - timedelta(days=1), ORDER[-1]

    def is_on(self, team: TeamInfo, d: date, kind: str) -> bool:
        return self.shift_of(team, d) == kind

    def default_handover_target(self, team: TeamInfo, now: datetime) -> TeamInfo | None:
        """移交时默认的接收班组。

        班组正在上班：按交接顺序交给下一个班次（常白班交给当天中班）。
        班组已下班（例如下班后才补录移交）：交给此刻在班的倒班班组。
        """
        d, k = self.shift_at(now)
        if self.is_on(team, d, k):
            return self.handover_target(team, d, k)
        return self.rotating_team_on(d, k)

    def receiving_slot(self, team: TeamInfo, now: datetime) -> tuple[date, str]:
        """接收班组拿到任务时归属的班次：正在上班则为当前班次，否则为它的下一个班次。"""
        d, k = self.shift_at(now)
        if self.is_on(team, d, k):
            return d, k
        return self.next_shift_of_team(team, d, k)
