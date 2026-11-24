"""项目和子项目：建项目、分给班组 / 个人、跨班组权限、不可移交、全部完成才闭合、改派、下班后自动移交。"""

import uuid
from datetime import timedelta

import pytest

from app import project_service
from app.db import SessionLocal
from app.models import AuditLog, Task
from app.schedule_service import load_schedule, local_now

from .conftest import login


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def lh(client, code):
    name = {"T1": "t1_leader1", "T2": "t2_leader1", "T3": "t3_leader1", "T4": "t4_leader1", "DAY": "day_leader1"}[code]
    return login(client, name, name)


def test_leader_creates_project(client, admin_h, teams):
    h1 = lh(client, "T1")
    w = client.post("/api/workers", headers=admin_h, json={"name": "Proj Person", "team_id": teams["T1"]}).json()
    body = {"name": "1# 球磨机大修", "lang": "zh", "transferable": True, "deadline": "2031-01-31",
            "subs": [{"content": "拆除衬板", "team_id": teams["T1"]}, {"content": "更换轴承", "worker_id": w["id"]}]}
    # 班长（本班组范围）不能把子项目分给别的班组
    bad = client.post("/api/projects", headers=h1, json=body | {"subs": [{"content": "x", "team_id": teams["T3"]}]})
    assert bad.status_code == 403
    r = client.post("/api/projects", headers=h1, json=body)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["team_id"] == teams["T1"] and p["total"] == 2 and p["open"] == 2 and p["can_manage"]
    assert p["name"]["zh"] == "1# 球磨机大修"
    person_sub = next(s for s in p["subs"] if s["lead"])
    assert person_sub["lead"]["id"] == w["id"] and person_sub["team_id"] == teams["T1"]
    assert all(s["project"]["id"] == p["id"] and s["project"]["total"] == 2 for s in p["subs"])
    # 成员不能建项目
    m = client.post("/api/workers", headers=admin_h, json={"name": "Proj Member", "team_id": teams["T1"]}).json()
    uid = client.put(f"/api/workers/{m['id']}/account", headers=admin_h, json={"password": "1111"}).json()["user_id"]
    mh = {"Authorization": "Bearer " + client.post("/api/auth/pin", json={"user_id": uid, "pin": "1111"}).json()["access_token"]}
    client.post("/api/auth/change-password", headers=mh, json={"old_password": "1111", "new_password": "2222"})
    assert client.post("/api/projects", headers=mh, json=body).status_code == 403
    assert any(x["id"] == p["id"] for x in client.get("/api/projects", headers=mh).json())  # 能看本班组的项目
    # 管理员可以分给任何班组
    r = client.post("/api/projects", headers=admin_h, json=body | {"team_id": teams["T2"], "subs": [
        {"content": "a", "team_id": teams["T3"]}, {"content": "b", "team_id": teams["T4"]}]})
    assert r.status_code == 201 and {s["team_id"] for s in r.json()["subs"]} == {teams["T3"], teams["T4"]}


def test_close_only_when_all_done(client, admin_h, teams):
    p = client.post("/api/projects", headers=admin_h, json={"name": "Close test", "lang": "en", "team_id": teams["T1"], "subs": [
        {"content": "s1", "team_id": teams["T1"]}, {"content": "s2", "team_id": teams["T1"]}, {"content": "s3", "team_id": teams["T1"]}]}).json()
    s1, s2, s3 = p["subs"]
    client.post(f"/api/tasks/{s1['id']}/status", headers=admin_h, json={"status": "done"})
    client.post(f"/api/tasks/{s2['id']}/discard", headers=admin_h, json={"reason": "not needed"})
    d = client.get(f"/api/projects/{p['id']}", headers=admin_h).json()
    assert (d["done"], d["discarded"], d["open"], d["closed_at"]) == (1, 1, 1, None)
    client.post(f"/api/tasks/{s3['id']}/status", headers=admin_h, json={"status": "done"})
    d = client.get(f"/api/projects/{p['id']}", headers=admin_h).json()
    assert d["open"] == 0 and d["closed_at"]
    assert any(x["id"] == p["id"] for x in client.get("/api/projects", headers=admin_h, params={"state": "closed"}).json())
    # 再加子项目 → 重新打开
    d = client.post(f"/api/projects/{p['id']}/subs", headers=admin_h, json={"lang": "en", "subs": [{"content": "s4", "team_id": teams["T1"]}]}).json()
    assert d["closed_at"] is None and d["total"] == 4


def test_not_transferable_and_reassign(client, admin_h, teams):
    p = client.post("/api/projects", headers=admin_h, json={"name": "Fixed", "lang": "en", "team_id": teams["T2"],
                                                            "transferable": False, "subs": [{"content": "only us", "team_id": teams["T2"]}]}).json()
    sub = p["subs"][0]
    assert sub["perms"]["handover"] is False and sub["project"]["transferable"] is False
    r = client.post("/api/handover", headers=admin_h, json={"task_ids": [sub["id"]], "to_team_id": teams["T3"]})
    assert r.status_code == 409
    # 改派给某个人：任务换到这个人的班组，带队人 = 他
    w = client.post("/api/workers", headers=admin_h, json={"name": "Reassign W", "team_id": teams["T4"]}).json()
    r = client.post(f"/api/projects/{p['id']}/subs/{sub['id']}/assign", headers=admin_h, json={"worker_id": w["id"]})
    assert r.status_code == 200 and r.json()["team_id"] == teams["T4"] and r.json()["lead"]["id"] == w["id"]
    # 改成可移交后就能移交了
    client.patch(f"/api/projects/{p['id']}", headers=admin_h, json={"transferable": True})
    assert client.get(f"/api/tasks/{sub['id']}", headers=admin_h).json()["perms"]["handover"] is True
    people = {x["worker_id"]: x for x in client.get("/api/projects/people", headers=admin_h).json()}
    assert people[w["id"]]["next_date"] is not None


def test_auto_handover_after_shift(client, admin_h, teams):
    """可移交项目：子项目所在班次结束 30 分钟后还没做完、那个班组不在班 → 自动交给此刻在班的主班组。"""
    with SessionLocal() as db:
        sched = load_schedule(db)
        now = local_now()
        d, k = sched.shift_at(now)
        main = sched.main_team_on(d, k)
        off = next(t for t in sched.teams if t.is_main and not sched.is_on(t, d, k))
    code = {v: c for c, v in teams.items()}
    p = client.post("/api/projects", headers=admin_h, json={"name": "Auto", "lang": "en", "team_id": off.id, "subs": [
        {"content": "carry on", "team_id": off.id}]}).json()
    fixed = client.post("/api/projects", headers=admin_h, json={"name": "Stay", "lang": "en", "team_id": off.id, "transferable": False,
                                                                "subs": [{"content": "stay", "team_id": off.id}]}).json()
    with SessionLocal() as db:  # 把两个子项目都放到两天前的班次（早就结束了）
        for tid in (p["subs"][0]["id"], fixed["subs"][0]["id"]):
            t = db.get(Task, tid)
            t.shift_date, t.shift_kind = d - timedelta(days=2), "day"
        db.commit()
        created = project_service.auto_handover(db, now)
        db.commit()
        assert [c.project_id for c in created] == [p["id"]]
        new = created[0]
        assert new.team_id == main.id and new.source_task_id == p["subs"][0]["id"]
        log = db.query(AuditLog).filter(AuditLog.entity == "task", AuditLog.entity_id == str(p["subs"][0]["id"]),
                                        AuditLog.action == "handover").all()
        assert log and all(l.user_id is None for l in log)  # 系统自动
    assert client.get(f"/api/tasks/{p['subs'][0]['id']}", headers=admin_h).json()["status"] == "handed_over"
    assert client.get(f"/api/tasks/{fixed['subs'][0]['id']}", headers=admin_h).json()["status"] == "not_started"
    d2 = client.get(f"/api/projects/{p['id']}", headers=admin_h).json()
    assert d2["total"] == 1 and d2["subs"][0]["team_id"] == main.id  # 只算链条最新的一条
    assert code[main.id]
