"""班组管理：新增长期 / 临时班组、不固定班组、班组互换、排班检查。"""

from datetime import date, timedelta

import pytest

from app.shifts import DAY, MIDDLE, NIGHT, OFF, Schedule, TeamInfo, coverage_problems

from .conftest import login

BASE = date(2026, 11, 1)
T = (TeamInfo(1, "rotating", 4), TeamInfo(2, "rotating", 6), TeamInfo(3, "rotating", 0),
     TeamInfo(4, "rotating", 2), TeamInfo(5, "day"))


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def test_temporary_and_manual_teams_pure():
    tmp = TeamInfo(6, "rotating", 0, date(2026, 12, 1), date(2026, 12, 10))  # 和 3 班同一个循环位置
    man = TeamInfo(7, "manual")
    s = Schedule(base_date=BASE, teams=(*T, tmp, man), overrides={(7, date(2026, 12, 5)): NIGHT})
    assert s.shift_of(tmp, date(2026, 11, 30)) == OFF  # 有效期之前休息
    assert s.shift_of(tmp, date(2026, 12, 1)) == s.shift_of(T[2], date(2026, 12, 1))
    assert s.shift_of(tmp, date(2026, 12, 11)) == OFF  # 结束后休息
    assert s.shift_of(man, date(2026, 12, 4)) == OFF and s.shift_of(man, date(2026, 12, 5)) == NIGHT
    # 主班组还是原来的倒班班组（排在前面）；临时班组也在「当班」名单里
    d = date(2026, 12, 1)
    k = s.shift_of(T[2], d)
    assert s.rotating_team_on(d, k).id == 3 and 6 in [t.id for t in s.teams_on(d, k)]
    # 原来的倒班班组整天休息、只有不固定班组上 → 它就是主班组
    s2 = Schedule(base_date=BASE, teams=(*T, man), overrides={(1, date(2026, 11, 21)): OFF, (7, date(2026, 11, 21)): DAY})
    assert s2.rotating_team_on(date(2026, 11, 21), DAY).id == 7


def test_coverage_problems():
    s = Schedule(base_date=BASE, teams=T, overrides={(1, date(2026, 11, 21)): OFF, (2, date(2026, 11, 21)): NIGHT})
    p = coverage_problems(s, date(2026, 11, 21), date(2026, 11, 22))
    assert (date(2026, 11, 21), DAY, "none", []) in p  # 1 班的白班没人上了（常白班不算）
    assert (date(2026, 11, 21), MIDDLE, "none", []) in p
    assert any(x[:3] == (date(2026, 11, 21), NIGHT, "multiple") for x in p)  # 2 班和 3 班都上夜班
    assert not [x for x in p if x[0] == date(2026, 11, 22)]


def test_multiple_day_teams_pair_with_day_shift():
    day2 = TeamInfo(8, "day")
    s = Schedule(base_date=BASE, teams=(*T, day2))
    d = date(2026, 11, 23)  # 周一
    rot = s.rotating_team_on(d, DAY)
    assert {t.id for t in s.paired_teams(day2, d)} == {rot.id, 5}
    assert {t.id for t in s.paired_teams(rot, d)} == {5, 8}


def test_team_crud(client, admin_h, leader_h):
    body = {"name_zh": "临时抢修班", "kind": "rotating", "day1": "2030-01-01",
            "active_from": "2030-01-01", "active_to": "2030-01-31"}
    assert client.post("/api/teams", headers=leader_h, json=body).status_code == 403
    assert client.post("/api/teams", headers=admin_h, json=body | {"name_zh": ""}).status_code == 400
    t = client.post("/api/teams", headers=admin_h, json=body).json()
    assert t["name_sr"] == t["name_en"] == "临时抢修班" and t["kind"] == "rotating"
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": "2029-12-31", "end": "2030-01-03"}).json()
    assert [c["shifts"][str(t["id"])] for c in cal] == [OFF, DAY, DAY, MIDDLE]  # 1 月 1 日是白班第 1 天
    # 改成不固定班组：没调班的日子都休息
    t2 = client.put(f"/api/teams/{t['id']}", headers=admin_h, json=body | {"kind": "manual", "name_en": "Repair crew"}).json()
    assert t2["kind"] == "manual" and t2["cycle_offset"] is None and t2["name_en"] == "Repair crew"
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": "2030-01-01", "end": "2030-01-01"}).json()
    assert cal[0]["shifts"][str(t["id"])] == OFF
    r = client.put("/api/team-shifts", headers=admin_h, json={"team_id": t["id"], "start": "2030-01-02", "end": "2030-01-02", "shift_kind": "night"})
    assert r.status_code == 200
    # 没用过的可以删（连同它的调班记录）；有员工后不能删
    w = client.post("/api/workers", headers=admin_h, json={"name": "Temp W", "team_id": t["id"]}).json()
    r = client.delete(f"/api/teams/{t['id']}", headers=admin_h)
    assert r.status_code == 409
    client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"team_id": None})
    assert client.delete(f"/api/teams/{t['id']}", headers=admin_h).status_code == 204
    assert t["id"] not in [x["id"] for x in client.get("/api/teams", headers=admin_h).json()]


def test_leader_team_shift_and_swap(client, admin_h, leader_h, teams):
    d = date(2030, 2, 4)
    cal = lambda: client.get("/api/shifts/calendar", headers=admin_h, params={"start": str(d), "end": str(d)}).json()[0]["shifts"]
    before = cal()
    one = {"team_id": teams["T1"], "start": str(d), "end": str(d), "shift_kind": "off"}
    assert client.put("/api/team-shifts", headers=leader_h, json=one).status_code == 200  # 班长调本班组
    assert cal()[str(teams["T1"])] == OFF
    assert client.put("/api/team-shifts", headers=leader_h, json=one | {"team_id": teams["T2"]}).status_code == 403
    cov = client.get("/api/shifts/coverage", headers=leader_h, params={"start": str(d), "end": str(d)}).json()
    if before[str(teams["T1"])] != OFF:
        assert any(p["shift_kind"] == before[str(teams["T1"])] and p["problem"] == "none" for p in cov)
    client.delete("/api/team-shifts", headers=leader_h, params={"team_id": teams["T1"], "start": str(d), "end": str(d)})
    assert cal() == before
    # 两个班组互换：班长只要其中一个是本班组
    sw = {"team_a": teams["T1"], "team_b": teams["T3"], "start": str(d), "end": str(d + timedelta(days=1))}
    assert client.post("/api/team-shifts/swap", headers=login(client, "t2_leader1", "t2_leader1"), json=sw).status_code == 403
    assert client.post("/api/team-shifts/swap", headers=leader_h, json=sw).status_code == 200
    after = cal()
    assert after[str(teams["T1"])] == before[str(teams["T3"])] and after[str(teams["T3"])] == before[str(teams["T1"])]
    assert client.get("/api/shifts/coverage", headers=admin_h, params={"start": str(d), "end": str(d)}).json() == []
    # 再换一次 = 恢复，不留覆盖记录
    client.post("/api/team-shifts/swap", headers=leader_h, json=sw)
    assert cal() == before
    assert client.get("/api/team-shifts", headers=admin_h, params={"start": str(d), "end": str(d + timedelta(days=1))}).json() == []


def test_config_allows_extra_rotating_team(client, admin_h):
    t = client.post("/api/teams", headers=admin_h, json={"name_zh": "5班", "kind": "rotating", "cycle_offset": 0}).json()
    cfg = client.get("/api/shifts/config", headers=admin_h).json()
    offs = {str(x["id"]): x["cycle_offset"] for x in client.get("/api/teams", headers=admin_h).json() if x["kind"] == "rotating"}
    body = {k: cfg[k] for k in ("base_date", "day_start", "middle_start", "night_start")} | {"offsets": offs}
    assert client.put("/api/shifts/config", headers=admin_h, json=body).status_code == 200  # 5 个倒班班组也能保存
    assert client.delete(f"/api/teams/{t['id']}", headers=admin_h).status_code == 204
