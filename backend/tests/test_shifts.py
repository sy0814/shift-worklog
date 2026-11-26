from datetime import date, datetime

from app.seed import TEAMS
from app.shifts import DAY, MIDDLE, NIGHT, OFF, Schedule, day_team, rotating

IDS = {code: i + 1 for i, (code, *_rest) in enumerate(TEAMS)}
TEAM = {code: rotating(IDS[code], off) if kind == "rotating" else day_team(IDS[code]) for code, _zh, _sr, _en, kind, off in TEAMS}
S = Schedule(teams=tuple(TEAM.values()),
             holidays=frozenset({date(2026, 11, 11)}))


def shifts_on(d):
    return {c: S.shift_of(t, d) for c, t in TEAM.items() if c != "DAY"}


def test_base_date():
    # 和工厂出勤表（2026 年 11 月）一致：1 日 3 班白（1）、4 班中（2）、2 班夜（3，10-31 23:00 开始）、1 班休（/）
    assert shifts_on(date(2026, 11, 1)) == {"T3": DAY, "T4": MIDDLE, "T2": NIGHT, "T1": OFF}


def test_documented_check_2026_11_21():
    assert shifts_on(date(2026, 11, 21)) == {"T1": DAY, "T2": MIDDLE, "T4": NIGHT, "T3": OFF}


def test_before_base_date():
    # 2 班 10-31、11-01 是夜班（11-01 的夜班 = 10-31 23:00 ~ 11-01 07:00），11-02 休息
    assert [S.shift_of(TEAM["T2"], date(2026, 10, 31)), S.shift_of(TEAM["T2"], date(2026, 11, 1)),
            S.shift_of(TEAM["T2"], date(2026, 11, 2))] == [NIGHT, NIGHT, OFF]


def test_every_day_exactly_one_of_each():
    for n in range(-100, 400):
        d = date.fromordinal(date(2026, 11, 1).toordinal() + n)
        assert sorted(shifts_on(d).values()) == sorted([DAY, MIDDLE, NIGHT, OFF])


def test_cycle_pattern():
    seq = [S.shift_of(TEAM["T3"], date(2026, 11, 1 + i)) for i in range(8)]
    assert seq == [DAY, DAY, MIDDLE, MIDDLE, OFF, NIGHT, NIGHT, OFF]  # 出勤表：1 1 2 2 / 3 3 /


def test_shift_at_boundaries():
    # 夜班记在下班那天
    assert S.shift_at(datetime(2026, 11, 22, 6, 59)) == (date(2026, 11, 22), NIGHT)
    assert S.shift_at(datetime(2026, 11, 22, 7, 0)) == (date(2026, 11, 22), DAY)
    assert S.shift_at(datetime(2026, 11, 22, 15, 0)) == (date(2026, 11, 22), MIDDLE)
    assert S.shift_at(datetime(2026, 11, 22, 22, 59)) == (date(2026, 11, 22), MIDDLE)
    assert S.shift_at(datetime(2026, 11, 22, 23, 0)) == (date(2026, 11, 23), NIGHT)
    assert S.shift_window(date(2026, 11, 23), NIGHT) == (datetime(2026, 11, 22, 23), datetime(2026, 11, 23, 7))


def test_night_handover_to_next_day_shift():
    # 11-01 07:00：2 班（11-01 的夜班）交给 3 班（11-01 白班）
    target = S.handover_target(TEAM["T2"], date(2026, 11, 1), NIGHT)
    assert target == TEAM["T3"]
    # 11-21：1 班白 -> 2 班中 -> 3 班（11-22 的夜班，11-21 23:00 开始）-> 11-22 白班
    assert S.handover_target(TEAM["T1"], date(2026, 11, 21), DAY) == TEAM["T2"]
    assert S.handover_target(TEAM["T2"], date(2026, 11, 21), MIDDLE) == TEAM["T3"]
    nxt = S.handover_target(TEAM["T3"], date(2026, 11, 22), NIGHT)
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
    # 3 班 11-22、11-23 夜班，11-24 休，下次是 11-25 白班
    assert S.next_shift_of_team(TEAM["T3"], date(2026, 11, 22), NIGHT) == (date(2026, 11, 23), NIGHT)
    assert S.next_shift_of_team(TEAM["T3"], date(2026, 11, 23), NIGHT) == (date(2026, 11, 25), DAY)


def test_default_handover_target():
    # 11-21 白班 10:00：1 班在班 → 交给 2 班（中班）
    assert S.default_handover_target(TEAM["T1"], datetime(2026, 11, 21, 10)) == TEAM["T2"]
    # 1 班 15:10 已下班补录 → 交给此刻在班的 2 班
    assert S.default_handover_target(TEAM["T1"], datetime(2026, 11, 21, 15, 10)) == TEAM["T2"]
    # 3 班 11-22 的夜班（11-21 23:00 开始），11-22 05:00 移交 → 11-22 白班的班组
    tgt = S.default_handover_target(TEAM["T3"], datetime(2026, 11, 22, 5))
    assert S.shift_of(tgt, date(2026, 11, 22)) == DAY
    # 常白班周五 10:00 → 当天中班
    assert S.default_handover_target(TEAM["DAY"], datetime(2026, 11, 20, 10)) == \
        S.rotating_team_on(date(2026, 11, 20), MIDDLE)


def test_receiving_slot():
    # 2 班 11-21 中班；白班时间收到 → 归属它当天的中班
    assert S.receiving_slot(TEAM["T2"], datetime(2026, 11, 21, 10)) == (date(2026, 11, 21), MIDDLE)
    # 4 班 11-21 的夜班早上已下班、11-22 休息，下一班是 11-23 白班
    assert S.receiving_slot(TEAM["T4"], datetime(2026, 11, 21, 10)) == (date(2026, 11, 23), DAY)


def test_extra_workday_for_day_team():
    s = Schedule(teams=tuple(TEAM.values()),
                 extra_workdays=frozenset({date(2026, 11, 21)}))  # 周六调休上班
    assert s.shift_of(TEAM["DAY"], date(2026, 11, 21)) == DAY
    assert s.shift_of(TEAM["DAY"], date(2026, 11, 22)) == OFF
    # 倒班不受影响
    assert s.shift_of(TEAM["T3"], date(2026, 11, 21)) == OFF


def test_recording_slot():
    # 11-21：1 班白班（07–15）
    assert S.recording_slot(TEAM["T1"], datetime(2026, 11, 21, 10)) == (date(2026, 11, 21), DAY)  # 上班中
    assert S.recording_slot(TEAM["T1"], datetime(2026, 11, 21, 16)) == (date(2026, 11, 21), DAY)  # 下班 1 小时内补录
    assert S.recording_slot(TEAM["T1"], datetime(2026, 11, 21, 20)) == (date(2026, 11, 22), DAY)  # 晚上提前安排明天
    # 4 班 11-22 休息、11-23 白班；11-22 凌晨提前安排 → 11-23 白班
    assert S.recording_slot(TEAM["T4"], datetime(2026, 11, 22, 3)) == (date(2026, 11, 23), DAY)
    # 常白班周一凌晨 → 当天白班；周五 16:00 刚下班 → 周五白班
    assert S.recording_slot(TEAM["DAY"], datetime(2026, 11, 23, 3)) == (date(2026, 11, 23), DAY)
    assert S.recording_slot(TEAM["DAY"], datetime(2026, 11, 20, 16)) == (date(2026, 11, 20), DAY)
