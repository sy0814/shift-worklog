"""巡查周期计算。2026-11-01 基准：3 班白1、4 班中1、1 班夜1、2 班休1；2026-11-21 周六：1 白、2 中、3 夜、4 休。"""

from datetime import date, datetime, time

from app.inspection_schedule import Rule, assignment, next_occurrence, upcoming
from app.shifts import DAY, MIDDLE, NIGHT, Schedule, day_team, rotating

T = {"T1": rotating(1, 4), "T2": rotating(2, 6), "T3": rotating(3, 0), "T4": rotating(4, 2), "DAY": day_team(5)}
S = Schedule(teams=tuple(T.values()), holidays=frozenset({date(2026, 11, 25)}))
AT = lambda *a: datetime(*a)


def test_daily_every_n():
    r = Rule(kind="daily", at_time=time(8), every_n=3, start_date=date(2026, 11, 1))
    assert upcoming(r, AT(2026, 11, 1, 7), S, 3) == [AT(2026, 11, 1, 8), AT(2026, 11, 4, 8), AT(2026, 11, 7, 8)]
    assert next_occurrence(r, AT(2026, 11, 1, 8), S) == AT(2026, 11, 4, 8)  # 严格晚于


def test_weekly():
    r = Rule(kind="weekly", at_time=time(10, 30), weekdays=[0, 3])  # 周一、周四
    assert upcoming(r, AT(2026, 11, 21, 0), S, 3) == [AT(2026, 11, 23, 10, 30), AT(2026, 11, 26, 10, 30), AT(2026, 11, 30, 10, 30)]


def test_monthly_clamps_to_last_day():
    r = Rule(kind="monthly", at_time=time(9), month_days=[31])
    assert upcoming(r, AT(2026, 11, 1), S, 3) == [AT(2026, 11, 30, 9), AT(2026, 12, 31, 9), AT(2027, 1, 31, 9)]
    r2 = Rule(kind="monthly", at_time=time(9), month_days=[30, 31])  # 2 月只触发一次
    assert [x.date() for x in upcoming(r2, AT(2027, 2, 1), S, 2)] == [date(2027, 2, 28), date(2027, 3, 30)]


def test_every_night_shift_on_duty():
    r = Rule(kind="shift", shift_kinds=[NIGHT], every_n=1, start_date=date(2026, 11, 1))
    occ = upcoming(r, AT(2026, 11, 21, 12), S, 2)
    assert occ == [AT(2026, 11, 21, 23), AT(2026, 11, 22, 23)]
    team, d, k = assignment(r, occ[0], S)
    assert (team, d, k) == (T["T3"], date(2026, 11, 21), NIGHT)


def test_every_second_day_shift_global():
    r = Rule(kind="shift", shift_kinds=[DAY], every_n=2, start_date=date(2026, 11, 20))
    assert [x.date() for x in upcoming(r, AT(2026, 11, 19), S, 3)] == [date(2026, 11, 20), date(2026, 11, 22), date(2026, 11, 24)]


def test_fixed_team_own_night_shifts():
    # 1 班自己的夜班：11-01、11-02、11-09、11-10 ...（8 天一循环中的位置 4、5）
    r = Rule(kind="shift", shift_kinds=[NIGHT], every_n=1, start_date=date(2026, 11, 1), assign="fixed", team_id=1)
    occ = upcoming(r, AT(2026, 11, 1), S, 4)
    assert [x.date() for x in occ] == [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 10)]
    assert all(x.time() == time(23) for x in occ)
    assert assignment(r, occ[0], S)[0] == T["T1"]
    # 每隔 2 个：只取第 1、3 个
    r.every_n = 2
    assert [x.date() for x in upcoming(r, AT(2026, 11, 1), S, 2)] == [date(2026, 11, 1), date(2026, 11, 9)]


def test_day_team_shift_skips_weekend_and_holiday():
    r = Rule(kind="shift", shift_kinds=[DAY], start_date=date(2026, 11, 20), assign="fixed", team_id=5)
    # 11-20 周五，11-21/22 周末，11-25 节假日
    assert [x.date() for x in upcoming(r, AT(2026, 11, 20, 8), S, 3)] == [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 26)]


def test_fixed_team_off_goes_to_next_shift():
    # 11-21 10:00 派给 4 班（休息到 11-23 白班）→ 归到它的下一个班次
    r = Rule(kind="daily", at_time=time(10), assign="fixed", team_id=4)
    team, d, k = assignment(r, AT(2026, 11, 21, 10), S)
    assert team == T["T4"] and (d, k) == (date(2026, 11, 23), DAY)
    # 在班班组：11-21 10:00 是 1 班白班；凌晨 2 点是前一天的夜班
    r2 = Rule(kind="daily", at_time=time(10))
    assert assignment(r2, AT(2026, 11, 21, 10), S)[0] == T["T1"]
    assert assignment(r2, AT(2026, 11, 22, 2), S)[1:] == (date(2026, 11, 21), NIGHT)


def test_invalid_rules():
    assert next_occurrence(Rule(kind="shift", shift_kinds=[]), AT(2026, 11, 1), S) is None
    assert next_occurrence(Rule(kind="weekly", weekdays=[]), AT(2026, 11, 1), S) is None
    assert next_occurrence(Rule(kind="shift", shift_kinds=[DAY], assign="fixed", team_id=99), AT(2026, 11, 1), S) is None
