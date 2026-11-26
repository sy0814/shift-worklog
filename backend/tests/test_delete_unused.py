"""删除没用过的员工 / 管理员账号：员工连同账号、排班记录一起删；用过的（有任务、出勤、登录过……）不能删，只能停用。"""

import uuid

import pytest

from .conftest import login


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def worker(client, h, teams, name):
    r = client.post("/api/workers", headers=h, json={"name": name, "employee_no": "D-" + uuid.uuid4().hex[:8],
                                                       "team_id": teams["T1"]})
    assert r.status_code == 201, r.text
    return r.json()


def test_delete_unused_worker_with_account(client, admin_h, leader_h, teams):
    w = worker(client, admin_h, teams, "录错的人")
    acc = client.put(f"/api/workers/{w['id']}/account", headers=admin_h, json={"password": "123456"}).json()
    assert acc["user_id"]
    assert client.delete(f"/api/workers/{w['id']}", headers=leader_h).status_code == 403  # 班长不能删名册
    assert client.delete(f"/api/workers/{w['id']}", headers=admin_h).status_code == 204
    listed = client.get("/api/workers", headers=admin_h, params={"include_inactive": True}).json()
    assert all(x["id"] != w["id"] for x in listed)
    assert all(u["id"] != acc["user_id"] for u in client.get("/api/users", headers=admin_h).json())
    hist = client.get("/api/audit", headers=admin_h, params={"entity": "worker"}).json()
    items = hist["items"] if isinstance(hist, dict) else hist
    assert any(x["action"] == "delete" and str(x["entity_id"]) == str(w["id"]) for x in items)
    assert client.delete(f"/api/workers/{w['id']}", headers=admin_h).status_code == 404


def test_used_worker_cannot_be_deleted(client, admin_h, leader_h, teams):
    # 有出勤记录
    a = worker(client, admin_h, teams, "有出勤的人")
    client.put("/api/attendance", headers=admin_h, json={"worker_id": a["id"], "day": "2026-12-03", "status": "leave"})
    r = client.delete(f"/api/workers/{a['id']}", headers=admin_h)
    assert r.status_code == 409 and "attendance" in r.json()["detail"]
    # 参与过任务
    b = worker(client, admin_h, teams, "干过活的人")
    t = client.post("/api/tasks", headers=admin_h, json={"client_id": str(uuid.uuid4()), "content": "x", "lang": "zh",
                                                         "team_id": teams["T1"]}).json()
    from app.db import SessionLocal
    from app.models import TaskWorker
    with SessionLocal() as db:
        db.add(TaskWorker(task_id=t["id"], worker_id=b["id"]))
        db.commit()
    r = client.delete(f"/api/workers/{b['id']}", headers=admin_h)
    assert r.status_code == 409 and "task_workers" in r.json()["detail"]
    # 账号登录过
    c = worker(client, admin_h, teams, "登录过的人")
    acc = client.put(f"/api/workers/{c['id']}/account", headers=admin_h, json={"password": "123456"}).json()
    assert acc["user_id"]
    from app.models import User, utcnow
    with SessionLocal() as db:  # 成员是点头像登录的，这里直接记一次登录
        db.get(User, acc["user_id"]).last_login_at = utcnow()
        db.commit()
    r = client.delete(f"/api/workers/{c['id']}", headers=admin_h)
    assert r.status_code == 409 and "login" in r.json()["detail"]
    # 定期巡查里固定了这个人
    d = worker(client, admin_h, teams, "巡查固定的人")
    ins = client.post("/api/inspections", headers=admin_h, json={
        "name": "删人测试巡查", "content": "看一下", "lang": "zh", "kind": "daily", "at_time": "08:00", "assign": "fixed",
        "team_id": teams["T1"], "worker_ids": [d["id"]], "start_date": "2030-01-01"})
    assert ins.status_code in (200, 201), ins.text
    r = client.delete(f"/api/workers/{d['id']}", headers=admin_h)
    assert r.status_code == 409 and "inspection_templates" in r.json()["detail"]
    # 用过的照样能停用
    assert client.patch(f"/api/workers/{a['id']}", headers=admin_h, json={"is_active": False}).json()["is_active"] is False


def test_delete_unused_admin_account(client, admin_h):
    u = client.post("/api/users", headers=admin_h, json={"username": "spare_admin", "password": "Spare2026!",
                                                       "full_name": "备用"}).json()
    me = client.get("/api/auth/me", headers=admin_h).json()
    assert client.delete(f"/api/users/{me['id']}", headers=admin_h).status_code == 400  # 不能删自己
    used = client.post("/api/users", headers=admin_h, json={"username": "used_admin", "password": "Used2026!",
                                                          "full_name": "用过"}).json()
    login(client, "used_admin", "Used2026!")
    r = client.delete(f"/api/users/{used['id']}", headers=admin_h)
    assert r.status_code == 409 and "login" in r.json()["detail"]
    assert client.delete(f"/api/users/{u['id']}", headers=admin_h).status_code == 204
    assert all(x["id"] != u["id"] for x in client.get("/api/users", headers=admin_h).json())
    # 名册里的人的账号：去名册删
    staff = next(x for x in client.get("/api/users", headers=admin_h).json() if x["worker_id"])
    assert client.delete(f"/api/users/{staff['id']}", headers=admin_h).status_code == 400
