"""班组管理（任意循环、主班组 / 合并显示、临时班组）、班组互换、排班检查、员工个人排班与班组变更记录。"""

from datetime import date, timedelta

import pytest

from app.shifts import (CYCLE, DAY, MIDDLE, NIGHT, OFF, WEEKDAYS, Cycle, Schedule, TeamInfo, coverage_problems,
                        day_team, rotating)

from .conftest import login

T = (rotating(1, 4), rotating(2, 6), rotating(3, 0), rotating(4, 2), day_team(5))


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def test_any_cycle_pure():
    # 12 天循环：白×4 中×4 夜×2 休×2；从 12-01 开始
    c = Cycle((DAY,) * 4 + (MIDDLE,) * 4 + (NIGHT,) * 2 + (OFF,) * 2, date(2026, 12, 1))
    assert [c.planned(date(2026, 12, 1) + timedelta(days=i)) for i in (0, 3, 4, 8, 10, 12)] == [DAY, DAY, MIDDLE, NIGHT, OFF, DAY]
    assert c.planned(date(2026, 11, 30)) == OFF  # 开始前一天 = 循环最后一天
    # 节假日休息：节假日休，调休上班日按主要班次上
    w = Cycle(WEEKDAYS, date(2026, 11, 2), holiday_off=True)
    assert w.planned(date(2026, 11, 25), holidays={date(2026, 11, 25)}) == OFF
    assert w.planned(date(2026, 11, 28), workdays={date(2026, 11, 28)}) == DAY
    assert Cycle((NIGHT, NIGHT, OFF), date(2026, 1, 1), True).work_shift == NIGHT


def test_merged_groups_pure():
    # 合并显示：常白班白班时并到白班主班组；临时 / 自定义班组上哪个班就并到哪个班
    extra = TeamInfo(6, Cycle((NIGHT, OFF), date(2026, 11, 21)))  # 11-21 夜班（3 班也是夜班）
    s = Schedule(teams=(*T, extra))
    d = date(2026, 11, 23)  # 周一：4 班白班
    assert [t.id for t in s.group_of(T[4], d)] == [4, 5]
    assert [t.id for t in s.group_of(T[3], d)] == [4, 5]
    assert [t.id for t in s.group_of(extra, date(2026, 11, 21))] == [3, 6]
    assert s.main_team_on(date(2026, 11, 21), NIGHT).id == 3
    # 主班组都不上、只有合并班组上的班：它自己就是那个班的班组
    s2 = Schedule(teams=(*T, extra), overrides={(3, date(2026, 11, 21)): OFF})
    assert s2.main_team_on(date(2026, 11, 21), NIGHT).id == 6
    assert [t.id for t in s2.group_of(extra, date(2026, 11, 21))] == [6]
    # 两个合并班组都上同一个班、没有主班组：合在一起
    extra2 = TeamInfo(7, Cycle((NIGHT,), date(2026, 1, 1)))
    s3 = Schedule(teams=(*T, extra, extra2), overrides={(3, date(2026, 11, 21)): OFF})
    assert [t.id for t in s3.group_of(extra2, date(2026, 11, 21))] == [6, 7]


def test_temporary_and_manual_teams_pure():
    tmp = TeamInfo(6, Cycle(CYCLE, date(2026, 11, 1)), active_from=date(2026, 12, 1), active_to=date(2026, 12, 10))
    man = TeamInfo(7)
    s = Schedule(teams=(*T, tmp, man), overrides={(7, date(2026, 12, 5)): NIGHT})
    assert s.shift_of(tmp, date(2026, 11, 30)) == OFF
    assert s.shift_of(tmp, date(2026, 12, 1)) == s.shift_of(T[2], date(2026, 12, 1))  # 和 3 班同一个循环
    assert s.shift_of(tmp, date(2026, 12, 11)) == OFF
    assert s.shift_of(man, date(2026, 12, 4)) == OFF and s.shift_of(man, date(2026, 12, 5)) == NIGHT


def test_worker_shift_pure():
    s = Schedule(teams=T, overrides={(1, date(2026, 11, 21)): OFF})
    week = Cycle((OFF, DAY, DAY, DAY, DAY, DAY, DAY), date(2026, 11, 23))  # 周一休
    assert s.worker_shift(T[0], None, date(2026, 11, 21)) == OFF  # 跟班组（含班组调班）
    assert s.worker_shift(T[0], week, date(2026, 11, 23)) == OFF
    assert s.worker_shift(T[0], week, date(2026, 11, 24)) == DAY
    assert s.worker_shift(T[0], week, date(2026, 11, 30)) == OFF


def test_coverage_problems():
    s = Schedule(teams=T, overrides={(1, date(2026, 11, 21)): OFF, (2, date(2026, 11, 21)): NIGHT})
    p = coverage_problems(s, date(2026, 11, 21), date(2026, 11, 22))
    assert (date(2026, 11, 21), DAY, "none", []) in p  # 周六，常白班也不上
    assert (date(2026, 11, 21), MIDDLE, "none", []) in p
    assert any(x[:3] == (date(2026, 11, 21), NIGHT, "multiple") for x in p)
    s2 = Schedule(teams=T, overrides={(4, date(2026, 11, 23)): OFF})  # 周一 4 班不上白班，只剩常白班
    assert (date(2026, 11, 23), DAY, "nomain", [5]) in coverage_problems(s2, date(2026, 11, 23), date(2026, 11, 23))


CYC12 = ["day"] * 4 + ["middle"] * 4 + ["night"] * 2 + ["off"] * 2


def test_team_crud(client, admin_h, leader_h):
    body = {"name_zh": "检修班", "kind": "cycle", "pattern": CYC12, "cycle_start": "2030-01-01",
            "is_main": False, "active_from": "2030-01-01", "active_to": "2030-01-31"}
    assert client.post("/api/teams", headers=leader_h, json=body).status_code == 403
    assert client.post("/api/teams", headers=admin_h, json=body | {"name_zh": ""}).status_code == 400
    assert client.post("/api/teams", headers=admin_h, json=body | {"pattern": ["off", "off"]}).status_code == 400
    assert client.post("/api/teams", headers=admin_h, json=body | {"pattern": ["x"]}).status_code == 400
    t = client.post("/api/teams", headers=admin_h, json=body).json()
    assert t["name_sr"] == t["name_en"] == "检修班" and t["pattern"] == CYC12 and not t["is_main"]
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": "2029-12-31", "end": "2030-01-05"}).json()
    assert [c["shifts"][str(t["id"])] for c in cal] == [OFF, DAY, DAY, DAY, DAY, MIDDLE]
    # 改成不固定：没调班的日子都休息
    t2 = client.put(f"/api/teams/{t['id']}", headers=admin_h, json=body | {"kind": "manual", "name_en": "Repair"}).json()
    assert t2["kind"] == "manual" and t2["pattern"] is None and t2["name_en"] == "Repair"
    r = client.put("/api/team-shifts", headers=admin_h, json={"team_id": t["id"], "start": "2030-01-02", "end": "2030-01-02", "shift_kind": "night"})
    assert r.status_code == 200
    w = client.post("/api/workers", headers=admin_h, json={"name": "Temp W", "team_id": t["id"]}).json()
    assert client.delete(f"/api/teams/{t['id']}", headers=admin_h).status_code == 409
    client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"team_id": None})
    # 换过班组的记录还引用着它 → 也不能删（保住历史出勤）
    assert client.delete(f"/api/teams/{t['id']}", headers=admin_h).status_code == 409


def test_edit_existing_team_cycle(client, admin_h, teams):
    """原来的班组也能直接编辑循环（例如把 1 班改成 12 天循环），改回去就恢复。"""
    t1 = next(x for x in client.get("/api/teams", headers=admin_h).json() if x["code"] == "T1")
    assert t1["pattern"] == list(CYCLE) and t1["is_main"] and t1["kind"] == "cycle"
    body = {k: t1[k] for k in ("name_zh", "name_sr", "name_en", "kind", "pattern", "cycle_start", "holiday_off", "is_main", "active_from", "active_to")}
    day = lambda: client.get("/api/shifts/calendar", headers=admin_h, params={"start": "2031-03-03", "end": "2031-03-03"}).json()[0]["shifts"][str(t1["id"])]
    before = day()
    client.put(f"/api/teams/{t1['id']}", headers=admin_h, json=body | {"pattern": ["night"], "cycle_start": "2031-01-01"})
    assert day() == NIGHT
    client.put(f"/api/teams/{t1['id']}", headers=admin_h, json=body)
    assert day() == before
    day_t = next(x for x in client.get("/api/teams", headers=admin_h).json() if x["code"] == "DAY")
    assert day_t["pattern"] == list(WEEKDAYS) and day_t["holiday_off"] and not day_t["is_main"]


def test_leader_team_shift_and_swap(client, admin_h, leader_h, teams):
    d = date(2030, 2, 4)
    cal = lambda: client.get("/api/shifts/calendar", headers=admin_h, params={"start": str(d), "end": str(d)}).json()[0]["shifts"]
    before = cal()
    one = {"team_id": teams["T1"], "start": str(d), "end": str(d), "shift_kind": "off"}
    assert client.put("/api/team-shifts", headers=leader_h, json=one).status_code == 200
    assert cal()[str(teams["T1"])] == OFF
    assert client.put("/api/team-shifts", headers=leader_h, json=one | {"team_id": teams["T2"]}).status_code == 403
    client.delete("/api/team-shifts", headers=leader_h, params={"team_id": teams["T1"], "start": str(d), "end": str(d)})
    assert cal() == before
    sw = {"team_a": teams["T1"], "team_b": teams["T3"], "start": str(d), "end": str(d + timedelta(days=1))}
    assert client.post("/api/team-shifts/swap", headers=login(client, "t2_leader1", "t2_leader1"), json=sw).status_code == 403
    assert client.post("/api/team-shifts/swap", headers=leader_h, json=sw).status_code == 200
    after = cal()
    assert after[str(teams["T1"])] == before[str(teams["T3"])] and after[str(teams["T3"])] == before[str(teams["T1"])]
    client.post("/api/team-shifts/swap", headers=leader_h, json=sw)
    assert cal() == before


def test_worker_personal_schedule_and_history(client, admin_h, leader_h, teams):
    """个人排班（每人休息日不同）+ 换班组后以前的出勤不变。"""
    w = client.post("/api/workers", headers=admin_h, json={"name": "Weekly W", "team_id": teams["DAY"]}).json()
    grid = lambda s, e, tid: client.get("/api/attendance", headers=admin_h, params={"start": s, "end": e, "team_id": tid}).json()
    # 从 2031-01-06（周一）起：个人 7 天循环，周二休、其他天白班
    pat = ["day", "off", "day", "day", "day", "day", "day"]
    body = {"effective_from": "2031-01-06", "team_id": teams["DAY"], "personal": True, "pattern": pat, "cycle_start": "2031-01-06"}
    assert client.put(f"/api/workers/{w['id']}/schedule", headers=leader_h, json=body).status_code == 403
    r = client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json=body)
    assert r.status_code == 200 and len(r.json()) == 2
    cells = grid("2031-01-03", "2031-01-12", teams["DAY"])["cells"][str(w["id"])]
    # 01-03 周五、01-04 周六还按常白班；01-06 起按个人：周二(07)休、周六(11)周日(12)上班
    assert [cells[f"2031-01-{d:02d}"]["shift_kind"] for d in (3, 4, 6, 7, 11, 12)] == ["day", None, "day", None, "day", "day"]
    # 从 2031-02-01 起调到 1 班、跟 1 班排班：1 月的出勤不变，2 月按 1 班
    body2 = {"effective_from": "2031-02-01", "team_id": teams["T1"], "personal": False}
    hist = client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json=body2).json()
    assert [h["effective_from"] for h in hist] == ["2000-01-01", "2031-01-06", "2031-02-01"]
    jan = grid("2031-01-06", "2031-01-12", teams["DAY"])
    assert str(w["id"]) in jan["cells"]  # 1 月还在常白班的出勤表里
    feb = grid("2031-02-01", "2031-02-10", teams["T1"])
    assert w["id"] in [x["id"] for x in feb["workers"]]
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": "2031-02-01", "end": "2031-02-10"}).json()
    assert [feb["cells"][str(w["id"])][c["day"]]["shift_kind"] or "off" for c in cal] == [c["shifts"][str(teams["T1"])] for c in cal]
    # 现在所属的班组还是常白班（变更还没到日子）
    assert next(x for x in client.get("/api/workers", headers=admin_h).json() if x["id"] == w["id"])["team_id"] == teams["DAY"]
    # 删掉一条变更；最早那条不能删
    assert client.delete(f"/api/workers/{w['id']}/schedule/2031-02-01", headers=admin_h).status_code == 200
    assert client.delete(f"/api/workers/{w['id']}/schedule/2000-01-01", headers=admin_h).status_code == 400


def test_roster_team_change_keeps_history(client, admin_h, teams):
    """名册里直接改班组：从今天起生效，以前的出勤还按原班组。"""
    from app.schedule_service import local_now

    today = local_now().date()
    w = client.post("/api/workers", headers=admin_h, json={"name": "Mover", "team_id": teams["T2"]}).json()
    past = (today - timedelta(days=20)).isoformat()
    before = client.get("/api/attendance", headers=admin_h, params={"start": past, "end": past, "team_id": teams["T2"]}).json()
    client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"team_id": teams["T3"]})
    after = client.get("/api/attendance", headers=admin_h, params={"start": past, "end": past, "team_id": teams["T2"]}).json()
    assert after["cells"][str(w["id"])] == before["cells"][str(w["id"])]
    hist = client.get(f"/api/workers/{w['id']}/schedule", headers=admin_h).json()
    assert [(h["effective_from"], h["team_id"]) for h in hist] == [("2000-01-01", teams["T2"]), (today.isoformat(), teams["T3"])]
