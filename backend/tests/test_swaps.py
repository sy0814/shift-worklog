"""临时调班：互换、批量顶班、调休上班。2026-11-21 是周六：1 班白、2 班中、3 班夜、4 班休。"""

import pytest

from .conftest import login


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


@pytest.fixture(scope="module")
def w(client, admin_h, teams):
    mk = lambda n, t: client.post("/api/workers", headers=admin_h, json={"name": n, "team_id": teams[t]}).json()["id"]
    return {"t1": mk("Swap T1", "T1"), "t4": mk("Swap T4", "T4"), "t3a": mk("Swap T3a", "T3"),
            "t3b": mk("Swap T3b", "T3"), "day": mk("Swap Day", "DAY")}


def cell(client, h, team_id, wid, day):
    g = client.get("/api/attendance", headers=h, params={"team_id": team_id, "start": day, "end": day}).json()
    return g, g["cells"].get(str(wid), {}).get(day)


def test_swap_across_teams(client, admin_h, leader_h, teams, w):
    day = "2026-11-21"
    r = client.post("/api/attendance/swap", headers=leader_h,
                    json={"day": day, "worker_a": w["t1"], "worker_b": w["t4"], "note": "家里有事"})
    assert r.status_code == 200, r.text
    _, c1 = cell(client, admin_h, teams["T1"], w["t1"], day)
    assert c1["status"] == "off" and c1["source"] == "manual"
    g, c4 = cell(client, admin_h, teams["T1"], w["t4"], day)
    assert w["t4"] in g["guest_ids"]  # 4 班的人出现在 1 班的出勤表里
    assert c4["status"] == "present" and c4["shift_kind"] == "day" and c4["team_id"] == teams["T1"]
    # 同样的班不能互换
    r = client.post("/api/attendance/swap", headers=admin_h, json={"day": day, "worker_a": w["t3a"], "worker_b": w["t3b"]})
    assert r.status_code == 400
    # 两人都不是本班组 → 不能操作
    t2 = login(client, "t2_leader1", "t2_leader1")
    r = client.post("/api/attendance/swap", headers=t2, json={"day": day, "worker_a": w["t3a"], "worker_b": w["t4"]})
    assert r.status_code == 403


def test_batch_borrow_for_my_team(client, admin_h, teams, w):
    t2 = login(client, "t2_leader1", "t2_leader1")
    body = {"worker_ids": [w["t3a"], w["t3b"]], "start": "2026-11-22", "end": "2026-11-23",
            "status": "present", "shift_kind": "middle", "team_id": teams["T2"], "note": "周末支援"}
    r = client.put("/api/attendance/batch", headers=t2, json=body)
    assert r.status_code == 200 and r.json()["updated"] == 4
    g, c = cell(client, admin_h, teams["T2"], w["t3a"], "2026-11-23")
    assert set(g["guest_ids"]) >= {w["t3a"], w["t3b"]} and c["shift_kind"] == "middle"
    # 不能把别的班组的人安排去第三个班组
    r = client.put("/api/attendance/batch", headers=t2, json=body | {"team_id": teams["T4"]})
    assert r.status_code == 403
    # 也不能给别的班组的人批请假
    r = client.put("/api/attendance/batch", headers=t2, json=body | {"status": "leave", "team_id": None})
    assert r.status_code == 403
    assert client.put("/api/attendance/batch", headers=admin_h,
                      json=body | {"start": "2026-11-01", "end": "2026-12-15"}).status_code == 400


def test_weekend_makeup_workday(client, admin_h, teams, w):
    _, c = cell(client, admin_h, teams["DAY"], w["day"], "2026-11-28")  # 周六
    assert c["status"] == "off"
    client.put("/api/holidays/2026-11-28", headers=admin_h, json={"day": "2026-11-28", "name": "调休上班", "kind": "workday"})
    _, c = cell(client, admin_h, teams["DAY"], w["day"], "2026-11-28")
    assert c["status"] == "present" and c["shift_kind"] == "day"
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": "2026-11-28", "end": "2026-11-28"}).json()
    assert cal[0]["workday"] is True and cal[0]["shifts"][str(teams["DAY"])] == "day"
    client.delete("/api/holidays/2026-11-28", headers=admin_h)


def test_cover_without_shift_uses_covered_teams_shift(client, admin_h, teams, w):
    # 11-29：3 班夜班（位置 4）。安排 1 班的人去顶 3 班，不指定班次 → 夜班
    client.put("/api/attendance/batch", headers=admin_h, json={
        "worker_ids": [w["t1"]], "start": "2026-11-29", "end": "2026-11-29", "status": "present", "team_id": teams["T3"]})
    _, c = cell(client, admin_h, teams["T3"], w["t1"], "2026-11-29")
    assert c["shift_kind"] == "night" and c["team_id"] == teams["T3"]
