"""车间（部门）：排班按车间分开算、导航页、按车间切换、车间管理员、跨车间移交。"""

import uuid
from datetime import date, timedelta

import pytest

from app.db import SessionLocal
from app.schedule_service import load_schedule, local_now
from app.shifts import CYCLE, DAY, MIDDLE, NIGHT, Cycle, Schedule, TeamInfo, coverage_problems, day_team, rotating

from .conftest import login


# ---------------- 排班引擎 ----------------
def _dept(team: TeamInfo, dept: int) -> TeamInfo:
    return TeamInfo(team.id, team.cycle, team.is_main, team.active_from, team.active_to, dept)


# 车间 1：1～4 班 + 常白班；车间 2：11～14 班（和车间 1 错开）
D1 = [_dept(rotating(1, 4), 1), _dept(rotating(2, 6), 1), _dept(rotating(3, 0), 1), _dept(rotating(4, 2), 1),
      _dept(day_team(5), 1)]
D2 = [_dept(rotating(11, 0), 2), _dept(rotating(12, 2), 2), _dept(rotating(13, 4), 2), _dept(rotating(14, 6), 2)]
S = Schedule(teams=tuple(D1 + D2))


def test_main_team_per_department():
    d = date(2026, 11, 2)  # 周一
    assert S.main_team_on(d, DAY, 1).id == 3 and S.main_team_on(d, DAY, 2).id == 11
    assert {t.id for t in S.teams_on(d, DAY, 1)} == {3, 5}
    assert {t.id for t in S.teams_on(d, DAY, 2)} == {11}


def test_merge_only_within_department():
    d = date(2026, 11, 2)
    assert [t.id for t in S.group_of(S.team(5), d)] == [3, 5]  # 常白班并到本车间的白班，不会并到车间 2 的 11 班
    assert [t.id for t in S.group_of(S.team(11), d)] == [11]


def test_handover_target_stays_in_department():
    from datetime import datetime

    now = datetime(2026, 11, 2, 10)  # 白班中
    assert S.default_handover_target(S.team(3), now).id == 4  # 车间 1 的中班
    assert S.default_handover_target(S.team(11), now).id == 12  # 车间 2 的中班
    assert S.default_handover_target(S.team(5), now).id == 4  # 常白班 → 本车间中班


def test_coverage_per_department():
    start, end = date(2026, 11, 1), date(2026, 11, 30)
    assert coverage_problems(S, start, end, 1) == []
    assert coverage_problems(S, start, end, 2) == []
    # 不分车间时，两个车间的主班组同时上同一个班 → 会被当成「多个主班组」
    assert any(p == "multiple" for _d, _k, p, _ids in coverage_problems(S, start, end))
    only2 = Schedule(teams=tuple(D1 + [_dept(TeamInfo(21, Cycle(CYCLE, date(2026, 11, 1)), True), 3)]))
    assert {p for _d, _k, p, _ids in coverage_problems(only2, start, end, 3)} == {"none"}


# ---------------- 接口 ----------------
@pytest.fixture(scope="module")
def d2(client, admin_h):
    r = client.post("/api/departments", headers=admin_h,
                    json={"name_zh": "选矿车间", "name_sr": "Flotacija", "name_en": "Flotation plant"})
    assert r.status_code == 201, r.text
    dep = r.json()
    h = {**admin_h, "X-Department": str(dep["id"])}
    ids = []
    for i, start in enumerate(["2026-11-01", "2026-10-30", "2026-10-28", "2026-10-26"]):  # 白 / 中 / 夜 / 休 各一个
        t = client.post("/api/teams", headers=h, json={
            "name_zh": f"选{i + 1}班", "name_sr": f"F{i + 1}", "name_en": f"F{i + 1}", "kind": "cycle",
            "pattern": list(CYCLE), "cycle_start": start, "is_main": True})
        assert t.status_code == 201, t.text
        assert t.json()["department_id"] == dep["id"]
        ids.append(t.json()["id"])
    return {"id": dep["id"], "h": h, "teams": ids}


def _mk_person(client, admin_h, name, role_id, username, team_id=None, dept_h=None):
    h = dept_h or admin_h
    w = client.post("/api/workers", headers=h, json={"name": name, "team_id": team_id})
    assert w.status_code == 201, w.text
    w = w.json()
    assert client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"role_id": role_id}).status_code == 200
    r = client.put(f"/api/workers/{w['id']}/account", headers=admin_h, json={"username": username, "password": "pass1234"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:  # 跳过「第一次登录先改密码」
        from app.models import User

        db.get(User, r.json()["user_id"]).must_change_password = False
        db.commit()
    return w, login(client, username, "pass1234")


@pytest.fixture(scope="module")
def roles(client, admin_h):
    return {r["code"]: r for r in client.get("/api/roles", headers=admin_h).json()}


def test_portal_is_public(client, d2):
    r = client.get("/api/departments")
    assert r.status_code == 200
    deps = {d["id"]: d for d in r.json()["departments"]}
    assert deps[d2["id"]]["name_en"] == "Flotation plant" and deps[d2["id"]]["teams"] == 4
    assert len(deps[d2["id"]]["on_duty_team_ids"]) == 1 and deps[d2["id"]]["on_duty_team_ids"][0] in d2["teams"]


def test_only_system_admin_manages_departments(client, admin_h, leader_h, d2):
    assert client.post("/api/departments", headers=leader_h, json={"name_zh": "x"}).status_code == 403
    assert client.delete(f"/api/departments/{d2['id']}", headers=admin_h).status_code == 409  # 有班组了
    d3 = client.post("/api/departments", headers=admin_h, json={"name_zh": "临时", "name_sr": "T", "name_en": "T"}).json()
    assert client.delete(f"/api/departments/{d3['id']}", headers=admin_h).status_code == 204


def test_views_follow_current_department(client, admin_h, leader_h, d2):
    now2 = client.get("/api/shifts/now", headers=d2["h"]).json()
    assert set(now2["current"]["team_ids"]) <= set(d2["teams"]) and len(now2["current"]["team_ids"]) == 1
    now1 = client.get("/api/shifts/now", headers=admin_h).json()
    assert not set(now1["current"]["team_ids"]) & set(d2["teams"])
    assert client.get("/api/board", headers=d2["h"]).json()["team_id"] in d2["teams"]
    cal = client.get("/api/shifts/calendar", headers=d2["h"], params={"start": "2026-11-01", "end": "2026-11-02"}).json()
    assert set(map(int, cal[0]["shifts"])) == set(d2["teams"])
    today = local_now().date()
    assert client.get("/api/shifts/coverage", headers=d2["h"],
                      params={"start": str(today), "end": str(today + timedelta(days=10))}).json() == []
    # 班长不能切换车间：带了请求头也还是自己的车间，别的车间的交接班不能看
    b = client.get("/api/board", headers={**leader_h, "X-Department": str(d2["id"])}).json()
    assert b["team_id"] not in d2["teams"]
    assert client.get("/api/board", headers=leader_h, params={"team_id": d2["teams"][0]}).status_code == 403
    me = client.get("/api/auth/me", headers=leader_h).json()
    assert me["department_id"] == 1 and me["can_switch_dept"] is False
    assert client.get("/api/auth/me", headers=admin_h).json()["can_switch_dept"] is True
    assert all(t["department_id"] == d2["id"]
               for t in client.get("/api/auth/teams", params={"department_id": d2["id"]}).json())


def test_cross_department_handover(client, admin_h, leader_h, d2):
    t = client.post("/api/tasks", headers=leader_h, json={
        "client_id": str(uuid.uuid4()), "content": "3# 浮选机叶轮需要选矿车间配合更换", "lang": "zh"}).json()
    target = d2["teams"][1]
    r = client.post("/api/handover", headers=leader_h, json={"task_ids": [t["id"]], "to_team_id": target, "note": "请配合"})
    assert r.status_code == 200, r.text
    new_id = r.json()[0]["id"]
    assert r.json()[0]["team_id"] == target
    ids = [x["id"] for x in client.get("/api/tasks", headers=d2["h"], params={"team_id": target}).json()["items"]]
    assert new_id in ids
    # 车间 1 的班长看不到交给别的车间后的新任务；车间 1 的任务列表也不会混进车间 2 的
    assert client.get(f"/api/tasks/{new_id}", headers=leader_h).status_code == 403
    assert new_id not in [x["id"] for x in client.get("/api/tasks", headers=admin_h, params={"limit": 200}).json()["items"]]
    # 系统建议的接班班组仍在本车间
    tgt = client.get("/api/handover/default", headers=leader_h, params={"team_id": t["team_id"]}).json()["to_team_id"]
    assert tgt not in d2["teams"]


def test_department_admin(client, admin_h, d2, roles):
    w, h = _mk_person(client, admin_h, "车间主任", roles["dept_admin"]["id"], "dept2_boss", dept_h=d2["h"])
    assert w["department_id"] == d2["id"] and w["team_id"] is None
    me = client.get("/api/auth/me", headers=h).json()
    assert me["department_id"] == d2["id"] and not me["can_switch_dept"] and me["perms"]["team.manage"] == "dept"
    # 本车间：加班组、加员工、改员工
    t = client.post("/api/teams", headers=h, json={"name_zh": "选矿检修", "name_sr": "Odr", "name_en": "Maint",
                                                   "kind": "manual"})
    assert t.status_code == 201 and t.json()["department_id"] == d2["id"]
    nw = client.post("/api/workers", headers=h, json={"name": "Marko", "team_id": d2["teams"][0]})
    assert nw.status_code == 201 and nw.json()["department_id"] == d2["id"]
    assert client.patch(f"/api/workers/{nw.json()['id']}", headers=h, json={"employee_no": "F-001"}).status_code == 200
    # 别的车间：不行
    assert client.post("/api/teams", headers=h, json={"name_zh": "x", "kind": "manual", "department_id": 1}).status_code == 403
    one = next(x for x in client.get("/api/workers", headers=admin_h).json() if x["department_id"] == 1)
    assert client.patch(f"/api/workers/{one['id']}", headers=h, json={"employee_no": "zz"}).status_code == 403
    assert client.post("/api/workers", headers=h, json={"name": "x", "team_id": 1}).status_code == 403
    # 不能给人设「全厂」范围的角色
    boss = client.post("/api/roles", headers=admin_h, json={
        "name_zh": "厂长", "name_sr": "Direktor", "name_en": "Plant manager", "login_mode": "password",
        "permissions": {"task.view": "all", "export": "all"}}).json()
    assert client.patch(f"/api/workers/{nw.json()['id']}", headers=h, json={"role_id": boss["id"]}).status_code == 403
    # 本车间的任务：可以分配给任何人（不限在岗）、可以导出、可以做 AI 分析权限检查
    assert client.get("/api/assignable", headers=h, params={"team_id": d2["teams"][0]}).json()["restricted"] is False
    assert client.get("/api/export/tasks", headers=h, params={"start": "2026-11-01", "end": "2026-11-02"}).status_code == 200
    assert client.get("/api/analysis", headers=h).status_code == 200
    assert client.get("/api/analysis", headers={**h, "X-Department": "1"}).status_code == 200  # 请求头被忽略，还是本车间


def test_factory_wide_role_can_switch(client, admin_h, d2, roles):
    boss = next(r for r in client.get("/api/roles", headers=admin_h).json() if r["name_zh"] == "厂长")
    _w, h = _mk_person(client, admin_h, "厂长", boss["id"], "plant_boss")
    assert client.get("/api/auth/me", headers=h).json()["can_switch_dept"] is True
    assert client.get("/api/board", headers={**h, "X-Department": str(d2["id"])}).json()["team_id"] in d2["teams"]
    assert client.get("/api/board", headers=h).json()["team_id"] not in d2["teams"]


def test_inspections_and_equipment_per_department(client, admin_h, d2):
    r = client.post("/api/inspections", headers=d2["h"], json={
        "name": "浮选槽巡检", "content": "检查液位", "lang": "zh", "kind": "daily", "at_time": "09:00"})
    assert r.status_code == 201 and r.json()["department_id"] == d2["id"]
    assert r.json()["id"] not in [x["id"] for x in client.get("/api/inspections", headers=admin_h).json()]
    prev = client.post("/api/inspections/preview", headers=d2["h"], json={
        "name": "x", "content": "x", "kind": "daily", "at_time": "09:00"}).json()
    assert all(o["team_id"] in d2["teams"] for o in prev)

    e = client.post("/api/equipment", headers=d2["h"], json={"code": "FL-01", "name": {"zh": "浮选机"}})
    assert e.status_code == 201 and e.json()["department_id"] == d2["id"]
    assert "FL-01" not in [x["code"] for x in client.get("/api/equipment", headers=admin_h).json()]
    assert "FL-01" in [x["code"] for x in client.get("/api/equipment", headers=d2["h"]).json()]


def test_worker_follows_team_department(client, admin_h, d2):
    w = client.post("/api/workers", headers=admin_h, json={"name": "Jovan", "team_id": 1}).json()
    assert w["department_id"] == 1
    w = client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"team_id": d2["teams"][2]}).json()
    assert w["department_id"] == d2["id"]
    with SessionLocal() as db:
        assert load_schedule(db).team(d2["teams"][2]).dept == d2["id"]


# ---------------- 不可移交（普通任务、巡查任务）----------------
def test_task_not_transferable(client, admin_h, leader_h):
    t = client.post("/api/tasks", headers=leader_h, json={
        "client_id": str(uuid.uuid4()), "content": "2# 球磨机衬板更换，本班跟到底", "lang": "zh", "transferable": False}).json()
    assert t["transferable"] is False and t["perms"]["handover"] is False
    r = client.post("/api/handover", headers=leader_h, json={"task_ids": [t["id"]]})
    assert r.status_code == 409 and r.json()["detail"] == "this task cannot be handed over"
    t = client.patch(f"/api/tasks/{t['id']}", headers=leader_h, json={"transferable": True}).json()
    assert t["transferable"] is True and t["perms"]["handover"] is True


def test_inspection_task_not_transferable(client, admin_h):
    from app import inspection_service
    from app.models import InspectionTemplate, Task

    r = client.post("/api/inspections", headers=admin_h, json={
        "name": "配电室巡检", "content": "检查配电柜温度", "lang": "zh", "kind": "daily", "at_time": "10:00",
        "transferable": False}).json()
    assert r["transferable"] is False
    run = client.post(f"/api/inspections/{r['id']}/run-now", headers=admin_h).json()
    with SessionLocal() as db:
        assert db.get(Task, run["task_id"]).transferable is False
    assert client.get(f"/api/tasks/{run['task_id']}", headers=admin_h).json()["perms"]["handover"] is False
