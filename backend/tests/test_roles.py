"""角色权限、名册里的人开账号、班组公共账号（点头像 + 个人密码）、首页按角色分块、只能分配同班次在岗的人。"""

import io
import uuid

import pytest
from PIL import Image

from app.db import SessionLocal
from app.schedule_service import load_schedule, local_now

from .conftest import login


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


@pytest.fixture(scope="module")
def roles(client, admin_h):
    return {r["code"]: r for r in client.get("/api/roles", headers=admin_h).json()}


def _on_duty_team(teams):
    """现在在班的主班组（测试用它的人，才能被分配任务）。"""
    with SessionLocal() as db:
        s = load_schedule(db)
        d, k = s.shift_at(local_now())
        return s.main_team_on(d, k).id


def pin_login(client, user_id, pin):
    return client.post("/api/auth/pin", json={"user_id": user_id, "pin": pin})


def test_builtin_roles(client, admin_h, leader_h, roles):
    assert set(roles) >= {"leader", "deputy", "member"}
    assert roles["leader"]["login_mode"] == "password" and roles["leader"]["show_on_top"]
    assert roles["member"]["login_mode"] == "pin" and not roles["member"]["show_on_top"]
    assert roles["member"]["permissions"]["task.status"] == "self"
    assert client.post("/api/roles", headers=leader_h, json={"name_zh": "x"}).status_code == 403
    assert client.delete(f"/api/roles/{roles['leader']['id']}", headers=admin_h).status_code == 400
    defs = {d["key"]: d["scopes"] for d in client.get("/api/roles/perms", headers=leader_h).json()}
    assert defs["task.view"] == ["team", "dept", "all"] and "self" in defs["photo.upload"]
    # 原来的班长账号已关联到名册里的人
    me = client.get("/api/auth/me", headers=leader_h).json()
    assert me["worker_id"] and me["role_info"]["code"] == "leader"
    ws = {w["id"]: w for w in client.get("/api/workers", headers=admin_h).json()}
    assert ws[me["worker_id"]]["role_id"] == roles["leader"]["id"]  # 名册接口带角色


def test_member_team_login_and_permissions(client, admin_h, teams, roles):
    tid = _on_duty_team(teams)
    code = next(c for c, i in teams.items() if i == tid)
    w = client.post("/api/workers", headers=admin_h, json={"name": f"Member {code}", "team_id": tid}).json()
    other = client.post("/api/workers", headers=admin_h, json={"name": f"Other {code}", "team_id": tid}).json()
    # 成员默认是班组账号：只设个人密码（4 位数字也行）
    assert client.put(f"/api/workers/{w['id']}/account", headers=admin_h, json={"password": "12"}).status_code == 422
    acc = client.put(f"/api/workers/{w['id']}/account", headers=admin_h, json={"password": "1234"}).json()
    assert acc["login_mode"] == "pin" and acc["user_id"]
    client.put(f"/api/workers/{other['id']}/account", headers=admin_h, json={"password": "1234"})  # 两人同一个密码也没关系
    # 登录页：班组 → 人（头像 + 名字）→ 个人密码
    assert any(t["id"] == tid for t in client.get("/api/auth/teams").json())
    people = {p["name"]: p for p in client.get(f"/api/auth/teams/{tid}/people").json()}
    assert f"Member {code}" in people
    assert client.post("/api/auth/login", data={"username": f"w{w['id']}", "password": "1234"}).status_code == 401
    r = pin_login(client, acc["user_id"], "1234")
    assert r.status_code == 200 and r.json()["user"]["perms"]["task.create"] == "none"
    mh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    # 管理员设的密码：必须先改密码才能用
    assert r.json()["user"]["must_change_password"] is True
    assert client.get("/api/tasks", headers=mh).status_code == 403
    assert client.post("/api/auth/change-password", headers=mh, json={"old_password": "1234", "new_password": "8765"}).status_code == 204
    # 成员看不到「为什么？」（排班解释），管理员能看
    assert client.get(f"/api/explain/worker/{w['id']}", headers=mh, params={"day": "2026-11-25"}).status_code == 403
    assert client.get(f"/api/explain/worker/{w['id']}", headers=admin_h, params={"day": "2026-11-25"}).status_code == 200

    # 班长建两条任务：一条有这个成员，一条没有
    lead = next(x for x in client.get("/api/users", headers=admin_h).json() if x["team_id"] == tid and x["role"] == "staff"
                and x["username"].endswith("leader1"))
    lh = login(client, lead["username"], lead["username"])
    new = lambda **kw: client.post("/api/tasks", headers=lh, json={"client_id": str(uuid.uuid4()), "content": "M test", "lang": "en"} | kw)
    mine = new(worker_ids=[w["id"]]).json()
    notmine = new(worker_ids=[other["id"]]).json()
    # 任务页「我的任务」= 按自己筛（worker_id）
    ids = [x["id"] for x in client.get("/api/tasks", headers=mh, params={"worker_id": w["id"]}).json()["items"]]
    assert mine["id"] in ids and notmine["id"] not in ids
    assert mine["perms"]["edit"] and mine["perms"]["status"]
    # 成员：能看本班组的，能开始 / 完成自己的，不能改、不能动别人的、不能新建
    seen = client.get(f"/api/tasks/{mine['id']}", headers=mh).json()
    assert seen["perms"] == {"edit": False, "status": True, "handover": False, "discard": False, "photo": True, "correct": False, "log": True}
    assert client.get(f"/api/tasks/{notmine['id']}", headers=mh).json()["perms"]["status"] is False
    assert client.post(f"/api/tasks/{notmine['id']}/status", headers=mh, json={"status": "in_progress"}).status_code == 403
    assert client.patch(f"/api/tasks/{mine['id']}", headers=mh, json={"content": "x"}).status_code == 403
    assert client.post("/api/tasks", headers=mh, json={"client_id": str(uuid.uuid4()), "content": "x", "lang": "en"}).status_code == 403
    r = client.post(f"/api/tasks/{mine['id']}/status", headers=mh, json={"status": "in_progress"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG")
    up = client.post(f"/api/tasks/{mine['id']}/attachments", headers=mh, files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")},
                     data={"client_id": str(uuid.uuid4())})
    assert up.status_code == 201 and up.json()  # 成员能传照片
    att = client.get(f"/api/tasks/{mine['id']}", headers=mh).json()["attachments"][0]
    assert att["can_delete"]  # 自己传的能删
    assert client.post(f"/api/tasks/{mine['id']}/status", headers=mh, json={"status": "done"}).json()["status"] == "done"
    # 别的班组的任务看不到
    others = [t for c, t in teams.items() if t != tid and c != "DAY"]
    page = client.get("/api/tasks", headers=mh, params={"team_id": others[0]}).json()
    assert page["total"] == 0
    # 管理员改角色权限：成员也能新建任务 → 立即生效
    perms = roles["member"]["permissions"] | {"task.create": "team"}
    client.put(f"/api/roles/{roles['member']['id']}", headers=admin_h, json=roles["member"] | {"permissions": perms})
    assert client.post("/api/tasks", headers=mh, json={"client_id": str(uuid.uuid4()), "content": "by member", "lang": "en"}).status_code == 201
    client.put(f"/api/roles/{roles['member']['id']}", headers=admin_h, json=roles["member"])
    # 操作记录里能看到角色权限的修改（对象名称 = 角色名）
    logs = client.get("/api/audit", headers=admin_h, params={"entity": "role"}).json()["items"]
    assert any(l["field"] == "perm:task.create" and l["label"] == "成员" for l in logs)
    assert client.get("/api/audit", headers=admin_h).status_code == 200


def test_pin_lockout_only_locks_that_person(client, admin_h, teams):
    w1 = client.post("/api/workers", headers=admin_h, json={"name": "Lock A", "team_id": teams["T2"]}).json()
    w2 = client.post("/api/workers", headers=admin_h, json={"name": "Lock B", "team_id": teams["T2"]}).json()
    u1 = client.put(f"/api/workers/{w1['id']}/account", headers=admin_h, json={"password": "4321"}).json()["user_id"]
    u2 = client.put(f"/api/workers/{w2['id']}/account", headers=admin_h, json={"password": "4321"}).json()["user_id"]
    for _ in range(5):
        assert pin_login(client, u1, "0000").status_code == 401
    assert pin_login(client, u1, "4321").status_code == 423  # 锁定，正确密码也不行
    assert pin_login(client, u2, "4321").status_code == 200  # 同班组别人不受影响
    assert client.post(f"/api/users/{u1}/unlock", headers=admin_h).status_code == 204
    assert pin_login(client, u1, "4321").status_code == 200


def test_leader_resets_member_pin_only_in_team(client, admin_h, teams, leader_h):
    mine = client.post("/api/workers", headers=admin_h, json={"name": "PIN mine", "team_id": teams["T1"]}).json()
    theirs = client.post("/api/workers", headers=admin_h, json={"name": "PIN theirs", "team_id": teams["T3"]}).json()
    assert client.put(f"/api/workers/{mine['id']}/account", headers=leader_h, json={"password": "5555"}).status_code == 200
    assert client.put(f"/api/workers/{theirs['id']}/account", headers=leader_h, json={"password": "5555"}).status_code == 403


def test_custom_role_on_top(client, admin_h, teams, roles):
    """自定义角色（安全员）：首页单独显示，用个人账号登录。"""
    r = client.post("/api/roles", headers=admin_h, json={"name_zh": "安全员", "login_mode": "password", "show_on_top": True,
                                                         "permissions": {"task.view": "all", "photo.upload": "team"}})
    assert r.status_code == 201
    role = r.json()
    assert role["permissions"]["task.edit"] == "none" and role["permissions"]["photo.upload"] == "team"
    tid = _on_duty_team(teams)
    w = client.post("/api/workers", headers=admin_h, json={"name": "Safety S", "team_id": tid}).json()
    client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"role_id": role["id"]})
    duty = client.get("/api/duty", headers=admin_h, params={"which": "current"}).json()
    top = [x["worker"]["id"] for x in duty["top"]]
    assert w["id"] in top
    assert all(w["id"] != x["worker"]["id"] for t in duty["teams"] for x in t["workers"])
    # 班长也在上面一块
    assert any(x["role_id"] == roles["leader"]["id"] for x in duty["top"]) or not any(
        x["role_id"] == roles["leader"]["id"] for t in duty["teams"] for x in t["workers"])
    assert client.delete(f"/api/roles/{role['id']}", headers=admin_h).status_code == 409  # 有人用着不能删


def test_assign_only_people_on_duty(client, admin_h, teams):
    """班长只能把任务分给同一班次在岗的人。"""
    tid = _on_duty_team(teams)
    lead = next(x for x in client.get("/api/users", headers=admin_h).json() if x["team_id"] == tid and x["username"].endswith("leader1"))
    lh = login(client, lead["username"], lead["username"])
    here = client.post("/api/workers", headers=admin_h, json={"name": "On duty", "team_id": tid}).json()
    off_team = next(t for c, t in teams.items() if c != "DAY" and t != tid)
    away = client.post("/api/workers", headers=admin_h, json={"name": "Off duty", "team_id": off_team}).json()
    a = client.get("/api/assignable", headers=lh).json()
    assert a["restricted"] and here["id"] in a["worker_ids"] and away["id"] not in a["worker_ids"]
    body = {"client_id": str(uuid.uuid4()), "content": "Assign test", "lang": "en"}
    r = client.post("/api/tasks", headers=lh, json=body | {"worker_ids": [away["id"]]})
    assert r.status_code == 400 and "Off duty" in r.json()["detail"]
    t = client.post("/api/tasks", headers=lh, json=body | {"client_id": str(uuid.uuid4()), "worker_ids": [here["id"]]}).json()
    assert client.patch(f"/api/tasks/{t['id']}", headers=lh, json={"worker_ids": [here["id"], away["id"]]}).status_code == 400
    # 管理员不限
    assert not client.get("/api/assignable", headers=admin_h, params={"team_id": tid}).json()["restricted"]
    assert client.patch(f"/api/tasks/{t['id']}", headers=admin_h, json={"worker_ids": [here["id"], away["id"]]}).status_code == 200


def test_new_worker_gets_default_password_and_must_change(client, admin_h, teams, leader_h):
    """新加的员工自动开账号（默认密码），第一次登录必须改密码；改的时候不能还用默认密码。"""
    assert client.get("/api/users/default-password", headers=leader_h).status_code == 403
    assert client.put("/api/users/default-password", headers=admin_h, json={"password": "123"}).status_code == 400
    assert client.put("/api/users/default-password", headers=admin_h, json={"password": "Abc2026"}).json()["password"] == "Abc2026"
    w = client.post("/api/workers", headers=admin_h, json={"name": "Brand New", "team_id": teams["T2"]}).json()
    acc = client.get(f"/api/workers/{w['id']}/account", headers=admin_h).json()
    assert acc["user_id"] and acc["login_mode"] == "pin" and acc["must_change_password"]
    r = client.post("/api/auth/pin", json={"user_id": acc["user_id"], "pin": "Abc2026"})
    assert r.status_code == 200 and r.json()["user"]["must_change_password"]
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/board", headers=h).json()["detail"] == "password change required"
    assert client.get("/api/auth/me", headers=h).status_code == 200 and client.get("/api/teams", headers=h).status_code == 200
    bad = client.post("/api/auth/change-password", headers=h, json={"old_password": "Abc2026", "new_password": "Abc2026"})
    assert bad.status_code == 400
    assert client.post("/api/auth/change-password", headers=h, json={"old_password": "Abc2026", "new_password": "4455"}).status_code == 204
    assert client.get("/api/board", headers=h).status_code == 200
    # 批量：给没账号的人开账号（这里都已经有了 → 0）
    assert client.post("/api/workers/accounts/open-all", headers=admin_h).json()["created"] >= 0
    # 个人账号角色（班长）：用户名 = 工号
    roles = {x["code"]: x["id"] for x in client.get("/api/roles", headers=admin_h).json()}
    w2 = client.post("/api/workers", headers=admin_h, json={"name": "New Lead", "employee_no": "E9001", "team_id": teams["T2"]}).json()
    client.patch(f"/api/workers/{w2['id']}", headers=admin_h, json={"role_id": roles["leader"]})
    acc2 = client.get(f"/api/workers/{w2['id']}/account", headers=admin_h).json()
    assert acc2["login_mode"] == "password" and acc2["username"] == "E9001"
    client.put("/api/users/default-password", headers=admin_h, json={"password": "123456"})
