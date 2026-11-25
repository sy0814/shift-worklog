"""「为什么？」：排班 / 出勤结果附带推理过程。解释和结果走同一段代码，不能对不上。"""

import random
from datetime import date, timedelta

from app import attendance_service as att
from app.shifts import CYCLE, Cycle, Schedule, TeamInfo, day_team, rotating
from app.worker_history import EPOCH, Entry

D = date(2032, 6, 9)  # 周三


def codes(trace):
    return [s["code"] for s in trace]


# ---------------- 纯函数 ----------------
def test_trace_does_not_change_results():
    """随机排班、随机日期：带 trace 和不带 trace 结果完全一样。"""
    rnd = random.Random(7)
    base = date(2026, 11, 1)
    teams = (rotating(1, 0), rotating(2, 2), rotating(3, 4), rotating(4, 6), day_team(5),
             TeamInfo(6, None, active_from=base + timedelta(days=10), active_to=base + timedelta(days=40)),
             TeamInfo(7, Cycle(("07:00-12:00,14:00-17:00", "off", "night"), base)))
    days = [base + timedelta(days=i) for i in range(120)]
    overrides = {(rnd.randint(1, 7), rnd.choice(days)): rnd.choice(["day", "middle", "night", "off", "08:00-16:00"])
                 for _ in range(40)}
    s = Schedule(teams, holidays=frozenset(rnd.sample(days, 6)), extra_workdays=frozenset(rnd.sample(days, 4)),
                 overrides=overrides)
    for d in days:
        for t in teams:
            tr: list = []
            assert s.shift_of(t, d, tr) == s.shift_of(t, d)
            assert tr, (t.id, d)  # 每个结果都至少有一条依据
            tr = []
            assert s.team_entry(t, d, tr) == s.team_entry(t, d)
        for entry in (Entry(EPOCH, 1, None), Entry(EPOCH, 5, Cycle(("day", "off"), base)), Entry(EPOCH, None, None)):
            tr = []
            assert att.resolve(s, entry, None, d, tr) == att.resolve(s, entry, None, d)


def test_team_trace_steps():
    s = Schedule((rotating(1, 0), day_team(5)), holidays=frozenset({D}), overrides={(1, D + timedelta(days=1)): "night"})
    tr: list = []
    s.shift_of(s.team(1), D, tr)
    assert codes(tr) == ["team_cycle", "cycle"]
    assert tr[1]["length"] == 8 and tr[1]["entry"] == CYCLE[tr[1]["pos"] - 1]
    tr = []
    assert s.shift_of(s.team(5), D, tr) == "off"  # 节假日
    assert codes(tr) == ["team_cycle", "cycle", "holiday"] and tr[2]["was"] == "day"
    tr = []
    assert s.shift_of(s.team(1), D + timedelta(days=1), tr) == "night"
    assert codes(tr) == ["team_cycle", "cycle", "team_override"]
    assert tr[-1]["planned"] == tr[1]["entry"] and tr[-1]["entry"] == "night"


def test_inactive_and_hours():
    t = TeamInfo(9, Cycle(("07:00-12:00,14:00-17:00",), D), active_from=D)
    s = Schedule((t,))
    tr: list = []
    assert s.shift_of(t, D - timedelta(days=1), tr) == "off" and codes(tr) == ["inactive"]
    tr = []
    assert s.shift_of(t, D, tr) == "day"
    assert codes(tr) == ["team_cycle", "cycle", "hours_kind"] and tr[-1]["kind"] == "day"


def test_resolve_cover_and_dropped_hours():
    class A:  # 出勤例外记录（只需要这些字段）
        status, shift_kind, team_id, source, note, updated_by, updated_at = "present", None, 2, "manual", "顶班", 1, None

    s = Schedule((TeamInfo(1, Cycle(("07:00-12:00,14:00-17:00",), D), is_main=True), rotating(2, 4)))
    tr: list = []
    r = att.resolve(s, Entry(EPOCH, 1, None), A, D, tr)
    assert r.team_id == 2 and r.shift_kind == s.shift_of(s.team(2), D)
    assert codes(tr)[:4] == ["membership", "team_cycle", "cycle", "hours_kind"]
    assert "attendance" in codes(tr) and "cover" in codes(tr)
    if r.shift_kind != "day":
        assert codes(tr)[-1] == "hours_dropped"


# ---------------- 接口 ----------------
def test_explain_worker_api(client, admin_h):
    t = client.post("/api/teams", headers=admin_h, json={
        "name_zh": "解释组", "kind": "cycle", "pattern": ["day", "day", "off"], "cycle_start": str(D), "is_main": False,
        "active_from": str(D)}).json()  # 有效期从 D 起，不影响其他测试的日期
    w = client.post("/api/workers", headers=admin_h, json={"name": "Why Person", "team_id": t["id"]}).json()

    def why(day):
        r = client.get(f"/api/explain/worker/{w['id']}", headers=admin_h, params={"day": str(day)})
        assert r.status_code == 200, r.text
        return r.json()

    x = why(D)
    assert x["result"]["status"] == "present" and x["result"]["shift_kind"] == "day"
    assert codes(x["steps"])[:3] == ["membership", "team_cycle", "cycle"]
    assert x["steps"][0]["always"] is True
    g = x["steps"][-1]
    assert g["code"] == "group" and g["alone"] is False and t["id"] in g["team_ids"]
    # 和出勤表结果一致
    grid = client.get("/api/attendance", headers=admin_h, params={"start": str(D), "end": str(D), "team_id": t["id"]}).json()
    cell = grid["cells"][str(w["id"])][str(D)]
    assert (cell["status"], cell["shift_kind"]) == (x["result"]["status"], x["result"]["shift_kind"])

    # 班组调班 → 写出谁设的、原本是什么
    r = client.put("/api/team-shifts", headers=admin_h, json={"team_id": t["id"], "start": str(D), "end": str(D),
                                                              "shift_kind": "middle", "note": "检修"})
    assert r.status_code == 200, r.text
    x = why(D)
    ov = next(s for s in x["steps"] if s["code"] == "team_override")
    assert ov["entry"] == "middle" and ov["planned"] == "day" and ov["note"] == "检修" and ov["by_name"]
    assert x["result"]["shift_kind"] == "middle"

    # 出勤例外：请假
    r = client.put("/api/attendance", headers=admin_h, json={"worker_id": w["id"], "day": str(D), "status": "leave", "note": "家里有事"})
    assert r.status_code == 200, r.text
    x = why(D)
    a = next(s for s in x["steps"] if s["code"] == "attendance")
    assert a["status"] == "leave" and a["note"] == "家里有事" and a["by_name"] and a["at"]
    assert x["result"]["status"] == "leave" and not any(s["code"] == "group" for s in x["steps"])

    # 加班
    d2 = D + timedelta(days=1)
    r = client.post("/api/overtime", headers=admin_h, json={"day": str(d2), "worker_ids": [w["id"]], "until": "17:00"})
    assert r.status_code in (200, 201), r.text
    assert any(s["code"] == "overtime" and s["hours"] == 2 for s in why(d2)["steps"])

    # 从某天起换成个人循环 → 名册那一步写出从哪天起、谁设的
    d3 = D + timedelta(days=5)
    r = client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json={
        "effective_from": str(d3), "team_id": t["id"], "personal": True, "pattern": ["night"], "cycle_start": str(d3)})
    assert r.status_code == 200, r.text
    x = why(d3)
    m = x["steps"][0]
    assert m["code"] == "membership" and m["personal"] and m["since"] == str(d3) and m["by_name"]
    assert codes(x["steps"])[1:3] == ["personal_cycle", "cycle"] and x["result"]["shift_kind"] == "night"


def test_explain_team_api(client, admin_h):
    t = client.post("/api/teams", headers=admin_h, json={"name_zh": "临时抢修", "kind": "manual", "is_main": False}).json()
    w = client.post("/api/workers", headers=admin_h, json={"name": "Brought In", "team_id": t["id"]}).json()

    def why():
        r = client.get(f"/api/explain/team/{t['id']}", headers=admin_h, params={"day": str(D)})
        assert r.status_code == 200, r.text
        return r.json()

    x = why()
    assert x["result"]["kind"] == "off" and codes(x["steps"]) == ["team_cycle"] and x["steps"][0]["manual"]
    client.put("/api/attendance/batch", headers=admin_h, json={"worker_ids": [w["id"]], "start": str(D), "end": str(D),
                                                                "status": "present", "shift_kind": "middle"})
    x = why()
    assert x["result"]["kind"] == "middle"
    ms = next(s for s in x["steps"] if s["code"] == "member_shift")
    assert [p["name"] for p in ms["workers"]] == ["Brought In"]
    assert x["steps"][-1]["code"] == "group"
    # 和排班日历一致
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": str(D), "end": str(D)}).json()[0]
    assert cal["shifts"][str(t["id"])] == "middle"
    assert client.get("/api/explain/team/999999", headers=admin_h, params={"day": str(D)}).status_code == 404
