from datetime import date, datetime

from app.seed import TEAMS
from app.shifts import DAY, MIDDLE, NIGHT, OFF, Schedule, TeamInfo

IDS = {code: i + 1 for i, (code, *_rest) in enumerate(TEAMS)}
TEAM = {code: TeamInfo(IDS[code], kind, off) for code, _zh, _sr, _en, kind, off in TEAMS}
S = Schedule(base_date=date(2026, 11, 1), teams=tuple(TEAM.values()),
             holidays=frozenset({date(2026, 11, 11)}))


def shifts_on(d):
    return {c: S.shift_of(t, d) for c, t in TEAM.items() if c != "DAY"}


def test_base_date():
    assert shifts_on(date(2026, 11, 1)) == {"T3": DAY, "T4": MIDDLE, "T1": NIGHT, "T2": OFF}


def test_documented_check_2026_11_21():
    assert shifts_on(date(2026, 11, 21)) == {"T1": DAY, "T2": MIDDLE, "T3": NIGHT, "T4": OFF}


def test_before_base_date():
    # 2 班 10-31 上的是最后一个夜班
    assert S.shift_of(TEAM["T2"], date(2026, 10, 31)) == NIGHT


def test_every_day_exactly_one_of_each():
    for n in range(-100, 400):
        d = date.fromordinal(date(2026, 11, 1).toordinal() + n)
        assert sorted(shifts_on(d).values()) == sorted([DAY, MIDDLE, NIGHT, OFF])


def test_cycle_pattern():
    seq = [S.shift_of(TEAM["T3"], date(2026, 11, 1 + i)) for i in range(8)]
    assert seq == [DAY, DAY, MIDDLE, MIDDLE, NIGHT, NIGHT, OFF, OFF]


def test_shift_at_boundaries():
    assert S.shift_at(datetime(2026, 11, 22, 6, 59)) == (date(2026, 11, 21), NIGHT)
    assert S.shift_at(datetime(2026, 11, 22, 7, 0)) == (date(2026, 11, 22), DAY)
    assert S.shift_at(datetime(2026, 11, 22, 15, 0)) == (date(2026, 11, 22), MIDDLE)
    assert S.shift_at(datetime(2026, 11, 22, 23, 0)) == (date(2026, 11, 22), NIGHT)


def test_night_handover_to_next_day_shift():
    # 11-01 07:00：2 班（10-31 夜班）交给 3 班
    target = S.handover_target(TEAM["T2"], date(2026, 10, 31), NIGHT)
    assert target == TEAM["T3"]
    # 11-21：1 班白 -> 2 班中 -> 3 班夜 -> 次日白班
    assert S.handover_target(TEAM["T1"], date(2026, 11, 21), DAY) == TEAM["T2"]
    assert S.handover_target(TEAM["T2"], date(2026, 11, 21), MIDDLE) == TEAM["T3"]
    nxt = S.handover_target(TEAM["T3"], date(2026, 11, 21), NIGHT)
    assert S.shift_of(nxt, date(2026, 11, 22)) == DAY


def test_day_team():
    day = TEAM["DAY"]
    assert S.shift_of(day, date(2026, 11, 20)) == DAY  # 周五
    assert S.shift_of(day, date(2026, 11, 21)) == OFF  # 周六
    assert S.shift_of(day, date(2026, 11, 11)) == OFF  # 节假日
    # 常白班默认交给当天中班
    assert S.handover_target(day, date(2026, 11, 20), DAY) == S.rotating_team_on(date(2026, 11, 20), MIDDLE)
    assert day in S.teams_on(date(2026, 11, 20), DAY)


def test_next_shift_of_team():
    # 11-21 夜班后 3 班休 11-23、11-24（位置 6、7），下次是 11-25 白班
    assert S.next_shift_of_team(TEAM["T3"], date(2026, 11, 22), NIGHT) == (date(2026, 11, 25), DAY)
