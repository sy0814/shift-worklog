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


def test_relink_takes_over_unused_auto_account(client, admin_h, teams):
    """原来的班长账号关联到名册里真正的那个人：那个人设成班长时自动开的账号没用过 → 自动删掉，旧账号接过来。"""
    roles = {r["code"]: r["id"] for r in client.get("/api/roles", headers=admin_h).json()}
    real = worker(client, admin_h, teams, "真正的班长")
    client.patch(f"/api/workers/{real['id']}", headers=admin_h, json={"role_id": roles["leader"]})
    auto = client.get(f"/api/workers/{real['id']}/account", headers=admin_h).json()
    assert auto["user_id"]  # 设成班长自动开了账号
    # 原来的班长账号（以前按人开、名册里是个占位的人）：自己建一个，别动共用的 t1_leader1 这些
    holder = worker(client, admin_h, teams, "old_leader_x")
    client.patch(f"/api/workers/{holder['id']}", headers=admin_h, json={"role_id": roles["leader"]})
    oid = client.put(f"/api/workers/{holder['id']}/account", headers=admin_h,
                     json={"username": "old_leader_x", "password": "Old2026!"}).json()["user_id"]
    old = next(u for u in client.get("/api/users", headers=admin_h).json() if u["id"] == oid)
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:  # 用过：不用强制改密码，直接登录
        db.get(User, oid).must_change_password = False
        db.commit()
    login(client, "old_leader_x", "Old2026!")  # 旧账号用过
    r = client.put(f"/api/users/{old['id']}/worker", headers=admin_h, json={"worker_id": real["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["worker_id"] == real["id"] and r.json()["full_name"] == "真正的班长"
    users = client.get("/api/users", headers=admin_h).json()
    assert all(u["id"] != auto["user_id"] for u in users)  # 空账号删掉了
    assert client.get(f"/api/workers/{real['id']}/account", headers=admin_h).json()["user_id"] == old["id"]
    login(client, "old_leader_x", "Old2026!")  # 照样用原来的用户名密码登录
    # 那个人自己的账号用过了 → 不能顶掉
    other = worker(client, admin_h, teams, "有自己账号的人")
    acc = client.put(f"/api/workers/{other['id']}/account", headers=admin_h, json={"password": "123456"}).json()
    from app.models import utcnow
    with SessionLocal() as db:
        db.get(User, acc["user_id"]).last_login_at = utcnow()
        db.commit()
    r = client.put(f"/api/users/{old['id']}/worker", headers=admin_h, json={"worker_id": other["id"]})
    assert r.status_code == 409


def test_reset_password_length_by_login_mode(client, admin_h, teams):
    """账号管理重设密码：点头像登录的成员 4 位就行（以前一律要 6 位，报「请求失败」）；管理账号至少 6 位。"""
    m = worker(client, admin_h, teams, "四位密码的成员")
    uid = client.put(f"/api/workers/{m['id']}/account", headers=admin_h, json={"password": "1234"}).json()["user_id"]
    assert client.post(f"/api/users/{uid}/reset-password", headers=admin_h, json={"password": "4321"}).status_code == 204
    adm = client.post("/api/users", headers=admin_h, json={"username": "pw_admin", "password": "Pw2026!!", "full_name": "x"}).json()
    r = client.post(f"/api/users/{adm['id']}/reset-password", headers=admin_h, json={"password": "4321"})
    assert r.status_code == 400 and "at least 6" in r.json()["detail"]
    assert client.post(f"/api/users/{adm['id']}/reset-password", headers=admin_h, json={"password": "654321"}).status_code == 204


def test_login_with_username_or_employee_no(client, admin_h, teams):
    """管理账号：用户名或工号都能登录（用户名改成别的以后，工号照样能用）。"""
    roles = {r["code"]: r["id"] for r in client.get("/api/roles", headers=admin_h).json()}
    w = client.post("/api/workers", headers=admin_h, json={"name": "Dejan", "employee_no": "10799001", "team_id": teams["T1"]}).json()
    client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"role_id": roles["leader"]})
    acc = client.put(f"/api/workers/{w['id']}/account", headers=admin_h, json={"username": "dejan", "password": "Dejan2026"}).json()
    assert acc["username"] == "dejan"
    for name in ("dejan", "10799001", " 10799001 "):
        r = client.post("/api/auth/login", data={"username": name, "password": "Dejan2026"})
        assert r.status_code == 200, (name, r.text)
        assert r.json()["user"]["id"] == acc["user_id"]
    assert client.post("/api/auth/login", data={"username": "10799001", "password": "wrong!!"}).status_code == 401
    # 成员（点头像登录的）用工号也不行，照样提示去用「个人账号」
    m = client.post("/api/workers", headers=admin_h, json={"name": "Member X", "employee_no": "10799002", "team_id": teams["T1"]}).json()
    client.put(f"/api/workers/{m['id']}/account", headers=admin_h, json={"password": "1234"})
    r = client.post("/api/auth/login", data={"username": "10799002", "password": "1234"})
    assert r.status_code == 401 and r.json()["detail"] == "use team login"
