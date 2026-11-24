"""排班推算（纯函数，不依赖数据库）。

倒班：8 天循环「白 白 中 中 夜 夜 休 休」，位置 0..7。
某日某班位置 = (起始位置 + 距基准天数) mod 8。
夜班归属开始的那一天：11-21 23:00 ~ 11-22 07:00 记为 11-21 的夜班。
常白班：周一到周五白班时段上班，周末和节假日休息。
不固定班组（manual，例如临时班组）：没有自己的循环，默认休息，只按「班组整体调班」安排上班。
临时班组有起止日期（active_from / active_to），范围以外一律休息。
交接顺序：夜班 → 白班 → 中班 → 夜班。
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

DAY, MIDDLE, NIGHT, OFF = "day", "middle", "night", "off"
CYCLE = (DAY, DAY, MIDDLE, MIDDLE, NIGHT, NIGHT, OFF, OFF)
ORDER = (DAY, MIDDLE, NIGHT)  # 一个「班次日」内的先后顺序


@dataclass(frozen=True)
class TeamInfo:
    id: int
    kind: str  # rotating（倒班）/ day（常白班型）/ manual（不固定，只按调班安排）
    cycle_offset: int | None = None
    active_from: date | None = None  # 临时班组：从哪天起有效（含）
    active_to: date | None = None  # 到哪天为止（含）；空 = 长期

    def active_on(self, d: date) -> bool:
        return (self.active_from is None or d >= self.active_from) and (self.active_to is None or d <= self.active_to)


@dataclass(frozen=True)
class Schedule:
    base_date: date
    teams: tuple[TeamInfo, ...]
    day_start: time = time(7)
    middle_start: time = time(15)
    night_start: time = time(23)
    holidays: frozenset[date] = frozenset()
    extra_workdays: frozenset[date] = frozenset()  # 调休上班的周末
    # 班组整体调班：(班组 id, 日期) → 当天改上的班（day / middle / night / off），优先于循环推算
    overrides: dict = field(default_factory=dict, hash=False, compare=False)

    # ---- 单个班组 ----
    def cycle_pos(self, team: TeamInfo, d: date) -> int:
        assert team.kind == "rotating" and team.cycle_offset is not None
        return (team.cycle_offset + (d - self.base_date).days) % len(CYCLE)

    def is_workday(self, d: date) -> bool:
        if d in self.extra_workdays:
            return True
        return d.weekday() < 5 and d not in self.holidays

    def shift_of(self, team: TeamInfo, d: date) -> str:
        if not team.active_on(d):
            return OFF
        o = self.overrides.get((team.id, d))
        if o is not None:
            return o
        return self.planned_shift_of(team, d)

    def planned_shift_of(self, team: TeamInfo, d: date) -> str:
        """不考虑整体调班时，按循环 / 工作日推算的班次。"""
        if not team.active_on(d):
            return OFF
        if team.kind == "rotating":
            return CYCLE[self.cycle_pos(team, d)]
        if team.kind == "day":
            return DAY if self.is_workday(d) else OFF
        return OFF  # manual：只按调班安排

    # ---- 某天 / 某时刻 ----
    def rotating_team_on(self, d: date, kind: str) -> TeamInfo | None:
        """某班次的「主班组」：优先倒班班组，没有的话用不固定班组（临时班组），常白班型不算。"""
        for want in ("rotating", "manual"):
            for t in self.teams:
                if t.kind == want and self.shift_of(t, d) == kind:
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

    # ---- 常白班搭班 ----
    def paired_teams(self, team: TeamInfo, d: date) -> list[TeamInfo]:
        """当天和本班组搭班的班组：常白班（型）上班的日子，常白班 ↔ 当天上白班的主班组。
        有多个常白班型班组时，它们和白班主班组合成一组。"""
        days = [t for t in self.teams if t.kind == "day" and self.shift_of(t, d) == DAY]
        if not days:
            return []
        rot = self.rotating_team_on(d, DAY)
        if rot is None:
            return []
        group = [rot, *days]
        if all(t.id != team.id for t in group):
            return []
        return [t for t in group if t.id != team.id]

    def recording_slot(self, team: TeamInfo, now: datetime, grace_hours: float = 2) -> tuple[date, str]:
        """班组录入任务时，任务归属哪个班次：
        正在上班 → 当前班次；刚下班不久（grace_hours 内，例如下班后补录）→ 刚结束的那个班次；
        否则（提前安排下个班的工作）→ 它的下一个班次。
        """
        d, k = self.shift_at(now)
        if self.is_on(team, d, k):
            return d, k
        pd, pk = d, k
        for _ in range(30 * len(ORDER)):  # 往回找这个班组最近的一个班
            pd, pk = self.prev_shift(pd, pk)
            if self.is_on(team, pd, pk):
                if now - self.shift_window(pd, pk)[1] <= timedelta(hours=grace_hours):
                    return pd, pk
                break
        return self.next_shift_of_team(team, d, k)


def coverage_problems(sched: Schedule, start: date, end: date) -> list[tuple[date, str, str, list[int]]]:
    """检查一段日期里每个班次有没有人上：(日期, 班次, 问题, 班组 id)。
    问题：none = 没有任何班组上（白班有常白班型也算没人，因为它不是主班组）；
    multiple = 两个以上主班组（倒班 / 不固定）同时上同一个班（可能是有意的，只提示）。"""
    out = []
    d = start
    while d <= end:
        for k in ORDER:
            main = [t for t in sched.teams if t.kind != "day" and sched.shift_of(t, d) == k]
            if not main:
                out.append((d, k, "none", []))
            elif len(main) > 1:
                out.append((d, k, "multiple", [t.id for t in main]))
        d += timedelta(days=1)
    return out
