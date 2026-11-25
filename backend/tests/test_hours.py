"""自定义上班时间（循环里某天写时间段，例如 07:00-12:00,14:00-17:00）。"""

from datetime import date, datetime

import pytest

from app.shifts import DAY, MIDDLE, NIGHT, OFF, Cycle, Schedule, TeamInfo, check_hours, day_team, parse_hours, rotating

T = (rotating(1, 4), rotating(2, 6), rotating(3, 0), rotating(4, 2), day_team(5))


def test_parse_and_check():
    assert parse_hours("day") is None
    assert check_hours(" 07:00-12:00 , 14:00-17:00") == "07:00-12:00,14:00-17:00"
    assert check_hours("22:00-06:00") == "22:00-06:00"  # 最后一段可以跨午夜
    for bad in ("7-12", "07:00-12:00,11:00-13:00", "20:00-02:00,03:00-05:00", "06:00-23:00", "25:00-26:00"):
        with pytest.raises(ValueError):
            check_hours(bad)


def test_entry_kind_by_overlap():
    s = Schedule(teams=T)
    assert s.entry_kind("07:00-12:00,14:00-17:00") == DAY  # 白班 7h、中班 2h
    assert s.entry_kind("13:00-21:00") == MIDDLE  # 白班 2h、中班 6h
    assert s.entry_kind("18:00-22:00") == MIDDLE
    assert s.entry_kind("22:00-06:00") == NIGHT
    assert s.entry_kind("02:00-06:00") == NIGHT  # 凌晨的算前一天的夜班
    assert s.entry_kind("off") == OFF


def test_entry_hours_and_team_with_custom_hours():
    split = TeamInfo(6, Cycle(("07:00-12:00,14:00-17:00",) * 5 + (OFF, OFF), date(2026, 11, 23)))
    s = Schedule(teams=(*T, split))
    d = date(2026, 11, 24)  # 周二
    assert s.team_entry(split, d) == "07:00-12:00,14:00-17:00"
    assert s.shift_of(split, d) == DAY and split in s.teams_on(d, DAY)
    assert s.entry_hours(s.team_entry(split, d), d) == [(datetime(2026, 11, 24, 7), datetime(2026, 11, 24, 12)),
                                                          (datetime(2026, 11, 24, 14), datetime(2026, 11, 24, 17))]
    assert s.entry_hours("night", d) == [(datetime(2026, 11, 24, 23), datetime(2026, 11, 25, 7))]
    assert s.entry_hours("02:00-06:00", d) == [(datetime(2026, 11, 25, 2), datetime(2026, 11, 25, 6))]
    assert s.shift_of(split, date(2026, 11, 28)) == OFF
    # 合并显示：并到白班主班组
    assert [t.id for t in s.group_of(split, d)][0] == s.main_team_on(d, DAY).id
    # 调休上班日：主要班次就是这个时间段
    assert Cycle(("07:00-12:00,14:00-17:00",) * 5 + (OFF, OFF), date(2026, 11, 23), True).work_shift == "07:00-12:00,14:00-17:00"


def test_personal_custom_hours():
    s = Schedule(teams=T)
    me = Cycle(("08:00-16:00", OFF), date(2026, 11, 24))
    assert s.worker_entry(T[0], me, date(2026, 11, 24)) == "08:00-16:00"
    assert s.worker_shift(T[0], me, date(2026, 11, 24)) == DAY
    assert s.worker_entry(T[0], me, date(2026, 11, 25)) == OFF


# ---------------- 接口 ----------------
@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def test_team_with_custom_hours_api(client, admin_h, teams):
    split = "07:00-12:00,14:00-17:00"
    body = {"name_zh": "检修组", "kind": "cycle", "pattern": [split] * 5 + ["off", "off"], "cycle_start": "2031-03-03",
            "is_main": False}
    bad = client.post("/api/teams", headers=admin_h, json=body | {"pattern": ["07:00-12:00,11:00-13:00"]})
    assert bad.status_code == 400 and "bad hours" in bad.json()["detail"]
    t = client.post("/api/teams", headers=admin_h, json=body | {"pattern": [" 07:00-12:00 , 14:00-17:00"] * 5 + ["off", "off"]}).json()
    assert t["pattern"][0] == split  # 规范化
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": "2031-03-03", "end": "2031-03-09"}).json()
    assert cal[0]["shifts"][str(t["id"])] == "day" and cal[0]["hours"][str(t["id"])] == split
    assert cal[5]["shifts"][str(t["id"])] == "off" and str(t["id"]) not in cal[5]["hours"]
    # 名册里的人跟这个班组：出勤格子带上班时间；加班从 17:00 算
    w = client.post("/api/workers", headers=admin_h, json={"name": "Split W", "team_id": t["id"]}).json()
    client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json={"effective_from": "2000-01-01", "team_id": t["id"]})
    g = client.get("/api/attendance", headers=admin_h, params={"start": "2031-03-03", "end": "2031-03-03", "team_id": t["id"]}).json()
    cell = g["cells"][str(w["id"])]["2031-03-03"]
    assert cell["shift_kind"] == "day" and cell["hours"] == split
    r = client.post("/api/overtime", headers=admin_h, json={"worker_ids": [w["id"]], "day": "2031-03-03", "until": "19:00"})
    assert r.status_code == 201, r.text
    people = client.get("/api/overtime/people", headers=admin_h, params={"start": "2031-03-03", "end": "2031-03-03"}).json()
    mine = next(p for p in people if p["worker_id"] == w["id"])
    assert mine["hours"] == 2.0  # 17:00 → 19:00（不是白班的 15:00）


def test_personal_custom_hours_api(client, admin_h, teams):
    w = client.post("/api/workers", headers=admin_h, json={"name": "Personal H", "team_id": teams["DAY"]}).json()
    body = {"effective_from": "2031-04-07", "team_id": teams["DAY"], "personal": True, "cycle_start": "2031-04-07",
            "pattern": ["08:00-16:00", "08:00-16:00", "off", "13:00-21:00", "13:00-21:00", "off", "off"]}
    assert client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json=body).status_code == 200
    g = client.get("/api/attendance", headers=admin_h, params={"start": "2031-04-07", "end": "2031-04-10", "team_id": teams["DAY"]}).json()
    c = g["cells"][str(w["id"])]
    assert [(c[d]["shift_kind"], c[d]["hours"]) for d in g["days"]] == [
        ("day", "08:00-16:00"), ("day", "08:00-16:00"), (None, None), ("middle", "13:00-21:00")]


def test_duty_helpers():
    from app.routers.duty import _in_hours, _working_now
    from app.attendance_service import DayAttendance

    s = Schedule(teams=T)
    d = date(2026, 11, 24)
    split = "07:00-12:00,14:00-17:00"
    assert _in_hours(s, split, d, datetime(2026, 11, 24, 9))
    assert not _in_hours(s, split, d, datetime(2026, 11, 24, 13))  # 午休
    row = {d: DayAttendance("present", "day", 9, "default", hours=split)}
    assert _working_now(s, row, d, datetime(2026, 11, 24, 16)) is row[d]  # 16:00 已是中班时段，但他还在上班
    assert _working_now(s, row, d, datetime(2026, 11, 24, 18)) is None


def test_duty_overlap_into_next_shift():
    """白班 07-12、14-17 的人算白班，但在中班名单里也列出来（到 17:00，计入在岗）。"""
    from app.routers.duty import _overlap
    from app.attendance_service import DayAttendance

    s = Schedule(teams=T)
    d = date(2026, 11, 24)
    split = "07:00-12:00,14:00-17:00"
    row = {d: DayAttendance("present", "day", 9, "default", hours=split)}
    mid_start, mid_end = s.shift_window(d, MIDDLE)
    a, f, u = _overlap(s, row, d, MIDDLE, mid_start, mid_end, None)  # 提前看下一个班（中班）
    assert a is row[d] and f == datetime(2026, 11, 24, 15) and u == datetime(2026, 11, 24, 17)
    assert _overlap(s, row, d, DAY, *s.shift_window(d, DAY), None) is None  # 本来就是白班的人：不算 overlap
    assert _overlap(s, row, d, NIGHT, *s.shift_window(d, NIGHT), None) is None  # 夜班没有重叠
    assert _overlap(s, row, d, MIDDLE, mid_start, mid_end, datetime(2026, 11, 24, 18)) is None  # 当前班次里已经过去了
    plain = {d: DayAttendance("present", "day", 9, "default")}
    assert _overlap(s, plain, d, MIDDLE, mid_start, mid_end, None) is None  # 普通白班的人不列
