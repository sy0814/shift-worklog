"""排班推算（纯函数，不依赖数据库）。

每个长期班组有一个**循环**：几天一循环、循环里每天上什么（白 / 中 / 夜 / 休）、循环第 1 天是哪天，
以及「节假日休息」开关（打开后节假日休息，调休上班的日子按它的主要班次上班）。
  例：倒班 1～4 班 = 8 天「白 白 中 中 休 夜 夜 休」；常白班 = 7 天「白×5 休 休」从周一开始 + 节假日休息。
不固定班组（cycle 为空，例如临时班组）：默认休息，只按「班组调班」安排上班。
临时班组有起止日期（active_from / active_to），范围以外一律休息。
主班组（is_main，例如 1～4 班）：首页卡片、交接班单独显示；其他班组上哪个班，就合并到这个班次的主班组里显示。
员工也可以有个人循环（见 worker_shift），不跟班组排班。
夜班归属结束（下班）的那一天：11-21 23:00 ~ 11-22 07:00 记为 11-22 的夜班（和工厂的出勤表一致，
表里 3 = 前一天 23:00 到当天 07:00）。所以一个「班次日」D 从 D-1 23:00 开始：夜班 → 白班 → 中班，到 D 23:00 结束。
交接顺序：夜班 → 白班 → 中班 → 下一天的夜班。
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

DAY, MIDDLE, NIGHT, OFF = "day", "middle", "night", "off"
KINDS = (DAY, MIDDLE, NIGHT, OFF)
CYCLE = (DAY, DAY, MIDDLE, MIDDLE, OFF, NIGHT, NIGHT, OFF)  # 四班三倒的 8 天循环（中班后休一天，夜班记在下班那天）
WEEKDAYS = (DAY, DAY, DAY, DAY, DAY, OFF, OFF)  # 周一到周五白班（从周一开始）
ORDER = (NIGHT, DAY, MIDDLE)  # 一个「班次日」内的先后顺序（夜班从前一天晚上开始）
MAX_CYCLE = 62

# 自定义上班时间：循环里某一天不写 day / middle / night / off，而写时间段，例如 "07:00-12:00,14:00-17:00"
# （最多 4 段，按时间先后；跨午夜的段、夜班开始（23:00）以后开始的段算前一天晚上，排在最前面，
#  例如 "22:00-06:00" = 前一天 22:00 到当天 06:00；"23:00-03:00,07:00-11:00" = 前一天 23:00 到当天 03:00，再加当天 07:00 到 11:00）。
# 分组、交接、任务归属班次时，按和白 / 中 / 夜哪个班重叠最多来算（见 Schedule.entry_kind）；
# 首页「现在在不在上班」、加班从几点算起，用实际的时间段（见 Schedule.entry_hours）。
# 推理过程（「为什么？」）：下面的函数可以带一个 trace 列表，按判定顺序追加每一步依据 {"code": ..., ...}。
# 结果和不带 trace 时完全一样（同一段代码），只是多记下来；业务代码平时不传。见 app/explain.py。
def note(trace: list | None, code: str, **kw) -> None:
    if trace is not None:
        trace.append({"code": code, **kw})


_HOURS_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


def parse_hours(entry: str) -> list[tuple[time, time]] | None:
    """"07:00-12:00,14:00-17:00" → [(07:00, 12:00), (14:00, 17:00)]；不是时间段（day / off ……）返回 None；格式不对抛 ValueError。"""
    if entry in KINDS:
        return None
    out = []
    for part in entry.split(","):
        m = _HOURS_RE.match(part.strip())
        if not m:
            raise ValueError(f"bad hours {entry!r}")
        h1, m1, h2, m2 = map(int, m.groups())
        if h1 > 23 or h2 > 24 or m1 > 59 or m2 > 59 or (h2 == 24 and m2):
            raise ValueError(f"bad hours {entry!r}")
        out.append((time(h1, m1), time(0, 0) if h2 == 24 else time(h2, m2)))
    return out


def _rel_minutes(a: time, b: time, night_start: time) -> tuple[int, int]:
    """一段时间在「班次日」里的分钟数（当天 00:00 = 0）。前一天晚上的段为负：跨午夜的段（例如 22:00-06:00），
    或者夜班开始（23:00）以后开始的段。"""
    x, y = a.hour * 60 + a.minute, b.hour * 60 + b.minute
    if y <= x:  # 跨午夜：从前一天晚上到当天
        return x - 24 * 60, y
    if x >= night_start.hour * 60 + night_start.minute:
        return x - 24 * 60, y - 24 * 60
    return x, y


def evening_part(a: time, b: time, night_start: time) -> bool:
    """这一段在前一天晚上开始（跨午夜，或夜班开始以后开始）。"""
    return b <= a or a >= night_start


def check_hours(entry: str, night_start: time = time(23)) -> str:
    """校验并规范化时间段写法；返回规范写法。"""
    iv = parse_hours(entry)
    if iv is None:
        return entry
    if not 1 <= len(iv) <= 4:
        raise ValueError("1..4 time ranges")
    total = 0
    prev_end = None
    for a, b in iv:
        x, y = _rel_minutes(a, b, night_start)
        if prev_end is not None and x < prev_end:
            raise ValueError("ranges must be in order and not overlap")
        prev_end = y
        total += y - x
    if total > 16 * 60:
        raise ValueError("at most 16 hours a day")
    return ",".join(f"{a:%H:%M}-{b:%H:%M}" if b != time(0, 0) else f"{a:%H:%M}-24:00" for a, b in iv)


@dataclass(frozen=True)
class Cycle:
    pattern: tuple[str, ...]  # 循环里每天的班
    start: date  # 循环第 1 天
    holiday_off: bool = False  # 节假日休息；调休上班日按主要班次上班

    @property
    def work_shift(self) -> str:
        """主要班次：循环里出现最多的班（可以是自定义时间段），调休上班日用。"""
        c = Counter(k for k in self.pattern if k != OFF)
        if not c:
            return DAY
        rank = {k: i for i, k in enumerate(ORDER)}
        return max(c, key=lambda k: (c[k], -rank.get(k, 9)))

    def planned(self, d: date, holidays=frozenset(), workdays=frozenset(), trace: list | None = None) -> str:
        """这一天循环里写的内容：day / middle / night / off，或自定义时间段（原样返回）。"""
        pos = (d - self.start).days % len(self.pattern)
        k = self.pattern[pos]
        note(trace, "cycle", pos=pos + 1, length=len(self.pattern), start=self.start, entry=k,
             holiday_off=self.holiday_off)
        if self.holiday_off:
            if d in holidays:
                note(trace, "holiday", was=k)
                return OFF
            if d in workdays and k == OFF:
                note(trace, "workday", entry=self.work_shift)
                return self.work_shift
        return k


ALL = object()  # teams_on / main_team_on 的 dept 参数：不限车间


@dataclass(frozen=True)
class TeamInfo:
    id: int
    cycle: Cycle | None = None  # None = 不固定（只按调班安排）
    is_main: bool = False
    active_from: date | None = None  # 临时班组：从哪天起有效（含）
    active_to: date | None = None  # 到哪天为止（含）；空 = 长期
    dept: int | None = None  # 车间 id

    @property
    def kind(self) -> str:
        return "cycle" if self.cycle else "manual"

    def active_on(self, d: date) -> bool:
        return (self.active_from is None or d >= self.active_from) and (self.active_to is None or d <= self.active_to)


def rotating(team_id: int, offset: int, base: date = date(2026, 11, 1)) -> TeamInfo:
    """按原来的写法（基准日在 8 天循环里的位置）构造倒班主班组。"""
    return TeamInfo(team_id, Cycle(CYCLE, base - timedelta(days=offset)), is_main=True)


def day_team(team_id: int, monday: date = date(2026, 11, 2)) -> TeamInfo:
    """常白班：周一到周五白班，节假日休息，合并显示。"""
    return TeamInfo(team_id, Cycle(WEEKDAYS, monday, holiday_off=True))


@dataclass(frozen=True)
class Schedule:
    teams: tuple[TeamInfo, ...]
    day_start: time = time(7)
    middle_start: time = time(15)
    night_start: time = time(23)
    holidays: frozenset[date] = frozenset()
    extra_workdays: frozenset[date] = frozenset()  # 调休上班的周末
    # 班组整体调班：(班组 id, 日期) → 当天改上的班（day / middle / night / off），优先于循环推算
    overrides: dict = field(default_factory=dict, hash=False, compare=False)
    # 非主班组（不固定班组、常白班型）班组本身这天休息、但有成员被单独安排上班（出勤页安排 / 个人循环）时，
    # 这个班组当天也算在上那个班（合并显示、交接班、能分配任务都按它算）。
    # member_fn(日期) → {日期: {班组 id: 班次}}（一次算一段日期，结果缓存）；为 None 时不算这一条
    member_fn: object = field(default=None, hash=False, compare=False)
    _member_cache: dict = field(default_factory=dict, hash=False, compare=False)

    def member_shift(self, team_id: int, d: date) -> str | None:
        """成员单独安排上班带出来的班组班次（只对非主班组、班组本身休息的日子有意义）。"""
        if self.member_fn is None:
            return None
        if d not in self._member_cache:
            self._member_cache.update(self.member_fn(d))
            self._member_cache.setdefault(d, {})
        return self._member_cache[d].get(team_id)

    # ---- 单个班组 ----
    def team(self, team_id: int | None) -> TeamInfo | None:
        return next((t for t in self.teams if t.id == team_id), None)

    def is_workday(self, d: date) -> bool:
        """日历上的工作日（周一到周五且不是节假日，或调休上班日），只用于显示。"""
        if d in self.extra_workdays:
            return True
        return d.weekday() < 5 and d not in self.holidays

    def cycle_entry(self, cycle: Cycle, d: date, trace: list | None = None) -> str:
        """循环里这一天写的内容（含节假日处理）：班次，或自定义时间段。"""
        return cycle.planned(d, self.holidays, self.extra_workdays, trace)

    def cycle_shift(self, cycle: Cycle, d: date) -> str:
        """这一天算哪个班（自定义时间段按重叠最多的班算）。"""
        return self.entry_kind(self.cycle_entry(cycle, d))

    def _slot_minutes(self) -> list[tuple[str, int, int]]:
        """三个班次在一个班次日里的起止（分钟，当天 00:00 = 0；夜班从前一天晚上开始 = 负数）。"""
        m = lambda t: t.hour * 60 + t.minute
        d, mid, n = m(self.day_start), m(self.middle_start), m(self.night_start)
        return [(NIGHT, n - 24 * 60, d), (DAY, d, mid), (MIDDLE, mid, n)]

    def entry_kind(self, entry: str) -> str:
        """班次写法原样返回；自定义时间段 → 和白 / 中 / 夜哪个班重叠最多就算哪个班（一样多取前面的）。"""
        iv = parse_hours(entry)
        if iv is None:
            return entry
        mins = [_rel_minutes(a, b, self.night_start) for a, b in iv]  # 夜班开始以后开始的段 = 前一天晚上
        best, best_overlap = DAY, -1
        for kind, s0, e0 in self._slot_minutes():
            ov = sum(max(0, min(y, e0) - max(x, s0)) for x, y in mins)
            if ov > best_overlap:
                best, best_overlap = kind, ov
        return best

    def entry_hours(self, entry: str, d: date) -> list[tuple[datetime, datetime]]:
        """这一天实际上班的时间段（本地时间）：自定义时间段按写的；白 / 中 / 夜按班次起止；休息为空。"""
        if entry == OFF:
            return []
        iv = parse_hours(entry)
        if iv is None:
            return [self.shift_window(d, entry)]
        out = []
        for a, b in iv:
            start = datetime.combine(d, a)
            if evening_part(a, b, self.night_start):  # 跨午夜或 23:00 以后开始：这个班次日的夜班，在前一天晚上
                start -= timedelta(days=1)
            end = datetime.combine(start.date(), b)
            if end <= start:
                end += timedelta(days=1)
            out.append((start, end))
        return out

    def entry_kind_traced(self, entry: str, trace: list | None = None) -> str:
        """同 entry_kind；自定义时间段时把「算作哪个班」记进 trace。"""
        k = self.entry_kind(entry)
        if trace is not None and k != entry:
            note(trace, "hours_kind", hours=entry, kind=k)
        return k

    def shift_of(self, team: TeamInfo, d: date, trace: list | None = None) -> str:
        k = self.entry_kind_traced(self.team_entry(team, d, trace), trace)
        if k == OFF and not team.is_main and team.active_on(d):
            if (team.id, d) in self.overrides:
                # 明确写下的优先于推算的：班组这天有班组调班，就按调班算，不再因为有成员上班改回在班
                if trace is not None and (m := self.member_shift(team.id, d)):
                    note(trace, "member_ignored", team_id=team.id, kind=m)
                return k
            m = self.member_shift(team.id, d)  # 成员被单独安排上班 → 班组也算在班
            if m:
                note(trace, "member_shift", team_id=team.id, kind=m)
                k = m
        return k

    def planned_entry(self, team: TeamInfo, d: date) -> str:
        """不考虑整体调班时，循环里这一天写的（班次或时间段）。"""
        if not team.active_on(d) or team.cycle is None:
            return OFF
        return self.cycle_entry(team.cycle, d)

    def planned_shift_of(self, team: TeamInfo, d: date) -> str:
        """不考虑整体调班时，按循环推算的班次。"""
        if not team.active_on(d) or team.cycle is None:
            return OFF
        return self.cycle_shift(team.cycle, d)

    def team_entry(self, team: TeamInfo, d: date, trace: list | None = None) -> str:
        """班组这一天的安排：整体调班优先；否则循环里写的。两者都可能是班次或自定义时间段。"""
        if not team.active_on(d):
            note(trace, "inactive", team_id=team.id, active_from=team.active_from, active_to=team.active_to)
            return OFF
        o = self.overrides.get((team.id, d))
        if o is not None:
            if trace is not None:
                note(trace, "team_cycle", team_id=team.id, manual=team.cycle is None)
                sub: list = []
                planned = self.cycle_entry(team.cycle, d, sub) if team.cycle else OFF
                trace.extend(sub)
                note(trace, "team_override", team_id=team.id, entry=o, planned=planned)
            return o
        note(trace, "team_cycle", team_id=team.id, manual=team.cycle is None)
        return self.cycle_entry(team.cycle, d, trace) if team.cycle else OFF

    def worker_entry(self, team: TeamInfo | None, personal: Cycle | None, d: date,
                     trace: list | None = None) -> str:
        """员工这一天的安排：有个人循环按个人的，否则跟班组。"""
        if personal is not None:
            note(trace, "personal_cycle")
            return self.cycle_entry(personal, d, trace)
        return self.team_entry(team, d, trace) if team else OFF

    # ---- 某天 / 某时刻 ----
    def main_team_on(self, d: date, kind: str, dept=ALL) -> TeamInfo | None:
        """某车间某班次的「主班组」：第一个上这个班的主班组；没有主班组上的话，用第一个上这个班的其他班组。"""
        on = self.teams_on(d, kind, dept)
        return next((t for t in on if t.is_main), on[0] if on else None)

    rotating_team_on = main_team_on  # 旧名字

    def teams_on(self, d: date, kind: str, dept=ALL) -> list[TeamInfo]:
        """某班次日某班次在班的所有班组（白班时可能包含常白班）。dept 给了就只看这个车间。"""
        return [t for t in self.teams if (dept is ALL or t.dept == dept) and self.shift_of(t, d) == kind]

    def depts(self) -> list:
        """排班里出现的车间（按班组顺序）。"""
        return list(dict.fromkeys(t.dept for t in self.teams))

    def shift_at(self, dt: datetime) -> tuple[date, str]:
        """本地时间 dt 属于哪个班次日的哪个班次。"""
        d, t = dt.date(), dt.time()
        if t < self.day_start:
            return d, NIGHT
        if t < self.middle_start:
            return d, DAY
        if t < self.night_start:
            return d, MIDDLE
        return d + timedelta(days=1), NIGHT  # 23:00 以后 = 第二天的夜班

    @staticmethod
    def next_shift(d: date, kind: str) -> tuple[date, str]:
        i = ORDER.index(kind)
        if i + 1 < len(ORDER):
            return d, ORDER[i + 1]
        return d + timedelta(days=1), ORDER[0]

    def shift_start(self, d: date, kind: str) -> datetime:
        """班次开始（本地 naive 时间）。夜班从前一天晚上开始。"""
        start_t = {DAY: self.day_start, MIDDLE: self.middle_start, NIGHT: self.night_start}[kind]
        return datetime.combine(d - timedelta(days=1) if kind == NIGHT else d, start_t)

    def shift_window(self, d: date, kind: str) -> tuple[datetime, datetime]:
        """班次起止（本地 naive 时间）。"""
        return self.shift_start(d, kind), self.shift_start(*self.next_shift(d, kind))

    def handover_target(self, team: TeamInfo, d: date, kind: str) -> TeamInfo | None:
        """默认移交对象：本车间下一个班次的主班组（常白班 07-15 下班 → 当天中班）。"""
        nd, nk = self.next_shift(d, kind)
        return self.main_team_on(nd, nk, team.dept)

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
        班组已下班（例如下班后才补录移交）：交给本车间此刻在班的主班组。
        """
        d, k = self.shift_at(now)
        if self.is_on(team, d, k):
            return self.handover_target(team, d, k)
        return self.main_team_on(d, k, team.dept)

    def receiving_slot(self, team: TeamInfo, now: datetime) -> tuple[date, str]:
        """接收班组拿到任务时归属的班次：正在上班则为当前班次，否则为它的下一个班次。"""
        d, k = self.shift_at(now)
        if self.is_on(team, d, k):
            return d, k
        try:
            return self.next_shift_of_team(team, d, k)
        except ValueError:  # 不固定班组最近没安排班：归到当前班次
            return d, k

    # ---- 合并显示（原「常白班搭班」）----
    def group_of(self, team: TeamInfo, d: date, kind: str | None = None) -> list[TeamInfo]:
        """班次 (d, kind) 里和 team 合并在一起的班组，主班组排第一。kind 默认是 team 当天的班。
        非主班组合并到同一车间这个班次的第一个主班组；没有主班组时，非主班组之间合在一起。"""
        kind = kind or self.shift_of(team, d)
        if kind == OFF or not self.is_on(team, d, kind):
            return [team]
        on = self.teams_on(d, kind, team.dept)
        mains = [t for t in on if t.is_main]
        others = [t for t in on if not t.is_main]
        if team.is_main:
            return [team, *others] if mains[0].id == team.id else [team]
        return [mains[0], *others] if mains else others

    def paired_teams(self, team: TeamInfo, d: date, kind: str | None = None) -> list[TeamInfo]:
        """和 team 合并显示的其他班组（交接班合并、两边班长都能操作）。"""
        return [t for t in self.group_of(team, d, kind) if t.id != team.id]

    def worker_shift(self, team: TeamInfo | None, personal: Cycle | None, d: date) -> str:
        """员工某天该上的班：有个人循环按个人的（不受班组整体调班影响），否则跟班组。"""
        if personal is not None:
            return self.cycle_shift(personal, d)
        return self.entry_kind(self.team_entry(team, d)) if team else OFF  # 班组自己的排班（不算成员带出来的）

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
        try:
            return self.next_shift_of_team(team, d, k)
        except ValueError:  # 不固定班组最近没安排班：归到当前班次
            return d, k


def coverage_problems(sched: Schedule, start: date, end: date, dept=ALL) -> list[tuple[date, str, str, list[int]]]:
    """检查某个车间一段日期里每个班次有没有人上：(日期, 班次, 问题, 班组 id)。dept 不给 = 所有班组当成一个车间。
    none = 没有任何班组上；nomain = 只有非主班组上（首页会单独显示它）；
    multiple = 两个以上主班组同时上同一个班（可能是有意的，只提示）。"""
    out = []
    d = start
    while d <= end:
        for k in ORDER:
            on = sched.teams_on(d, k, dept)
            mains = [t for t in on if t.is_main]
            if not on:
                out.append((d, k, "none", []))
            elif not mains:
                out.append((d, k, "nomain", [t.id for t in on]))
            elif len(mains) > 1:
                out.append((d, k, "multiple", [t.id for t in mains]))
        d += timedelta(days=1)
    return out
