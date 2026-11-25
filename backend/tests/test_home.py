"""首页：带队人员、常白班搭班权限、合并的交接班、在岗人员、头像。"""

import io
import uuid

import pytest
from PIL import Image

from app.db import SessionLocal
from app.schedule_service import load_schedule, local_now

from .conftest import login

LOGIN = {"T1": "t1_leader1", "T2": "t2_leader1", "T3": "t3_leader1", "T4": "t4_leader1", "DAY": "day_leader1"}


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


@pytest.fixture(scope="module")
def code_of(teams):
    return {v: k for k, v in teams.items()}


@pytest.fixture(scope="module")
def pair(teams, code_of):
    """常白班当前（或下一个）班次合并的主班组。"""
    with SessionLocal() as db:
        sched = load_schedule(db)
        day = sched.team(teams["DAY"])
        # 首页交接班显示常白班当前在上的班；下班后显示它的下一个班
        d, k = sched.shift_at(local_now())
        sd, sk = (d, k) if sched.is_on(day, d, k) else sched.next_shift_of_team(day, d, k)
        p = sched.paired_teams(day, sd, sk)
    return code_of[p[0].id] if p else None


def h(client, code):
    return login(client, LOGIN[code], LOGIN[code])


def new_task(client, hdr, **kw):
    r = client.post("/api/tasks", headers=hdr, json={"client_id": str(uuid.uuid4()), "content": "Home test", "lang": "en"} | kw)
    assert r.status_code == 201, r.text
    return r.json()


def test_lead_worker(client, admin_h, teams):
    ws = client.post("/api/workers/bulk", headers=admin_h, json={"names": ["Lead A", "Mem B", "Mem C"], "team_id": teams["T1"]}).json()
    a, b, c = (w["id"] for w in ws)
    h1 = h(client, "T1")
    t = new_task(client, h1, lead_worker_id=a, worker_ids=[a, b])  # 带队人也出现在参与人里 → 去重
    assert t["lead"]["name"] == "Lead A" and [w["name"] for w in t["workers"]] == ["Mem B"]
    # 带队人算参与：某人某天能查到
    day = client.get(f"/api/workers/{a}/day", headers=h1, params={"day": t["shift_date"]}).json()
    assert t["id"] in [x["id"] for x in day["tasks"]]
    # 换带队人、改参与人
    r = client.patch(f"/api/tasks/{t['id']}", headers=h1, json={"lead_worker_id": c, "worker_ids": [a, b]}).json()
    assert r["lead"]["name"] == "Mem C" and sorted(w["name"] for w in r["workers"]) == ["Lead A", "Mem B"]
    r = client.patch(f"/api/tasks/{t['id']}", headers=h1, json={"lead_worker_id": None}).json()
    assert r["lead"] is None and sorted(w["name"] for w in r["workers"]) == ["Lead A", "Mem B"]
    hist = client.get(f"/api/tasks/{t['id']}/history", headers=h1).json()
    leads = [(x["old_value"], x["new_value"]) for x in hist if x["field"] == "lead_worker"]
    assert leads == [("Lead A", "Mem C"), ("Mem C", None)]
    # 只改带队人，不传 worker_ids：参与人保持不变
    r = client.patch(f"/api/tasks/{t['id']}", headers=h1, json={"lead_worker_id": b}).json()
    assert r["lead"]["name"] == "Mem B" and [w["name"] for w in r["workers"]] == ["Lead A"]


def test_day_team_pairing_permission(client, teams, pair):
    hd = h(client, "DAY")
    day_task = new_task(client, hd, content="Day team task")
    others = [c for c in ("T1", "T2", "T3", "T4") if c != pair]
    # 不搭班的倒班班长：看得到但不能改
    ho = h(client, others[0])
    assert client.get(f"/api/tasks/{day_task['id']}", headers=ho).json()["can_edit"] is False
    assert client.post(f"/api/tasks/{day_task['id']}/status", headers=ho, json={"status": "in_progress"}).status_code == 403
    if pair is None:
        pytest.skip("今天常白班不上班，没有搭班")
    hp = h(client, pair)
    assert client.get(f"/api/tasks/{day_task['id']}", headers=hp).json()["can_edit"] is True
    assert client.post(f"/api/tasks/{day_task['id']}/status", headers=hp, json={"status": "in_progress"}).status_code == 200
    rot_task = new_task(client, hp, content="Rotating team task")
    assert client.get(f"/api/tasks/{rot_task['id']}", headers=hd).json()["can_edit"] is True


def test_board_merges_day_team(client, admin_h, teams, pair):
    hd = h(client, "DAY")
    t = new_task(client, hd, content="Merged board task")
    b = client.get("/api/board", headers=hd).json()  # 不传班组 = 本班组
    assert t["id"] in [x["id"] for x in b["todo"]]
    if pair is None:
        assert b["team_ids"] == [teams["DAY"]]
        return
    assert b["team_ids"] == [teams[pair], teams["DAY"]] and b["team_id"] == teams[pair]
    b2 = client.get("/api/board", headers=h(client, pair)).json()
    assert t["id"] in [x["id"] for x in b2["todo"]] and b2["team_ids"] == b["team_ids"]
    # 别的倒班班组看不到常白班的任务
    other = next(c for c in ("T1", "T2", "T3", "T4") if c != pair)
    b3 = client.get("/api/board", headers=admin_h, params={"team_id": teams[other]}).json()
    assert t["id"] not in [x["id"] for x in b3["todo"]] and b3["team_ids"] == [teams[other]]


def test_board_default_for_admin_is_on_duty_team(client, admin_h):
    now = client.get("/api/shifts/now", headers=admin_h).json()
    b = client.get("/api/board", headers=admin_h).json()
    assert b["team_id"] in now["current"]["team_ids"]


def test_duty(client, admin_h, teams):
    d = client.get("/api/duty", headers=admin_h).json()
    assert d["can_add"] is True and d["main_team_id"] in [x["team_id"] for x in d["teams"]] + [None]
    main = d["main_team_id"]
    if main is None:
        return
    code = next(c for c, i in teams.items() if i == main)
    ws = client.post("/api/workers/bulk", headers=admin_h, json={"names": ["Duty Busy", "Duty Idle", "Duty Leave", "Duty Assigned"], "team_id": main}).json()
    busy, idle, leave, assigned = ws
    client.put("/api/attendance", headers=admin_h, json={"worker_id": leave["id"], "day": d["shift_date"], "status": "leave"})
    new_task(client, h(client, code), content="Busy work", worker_ids=[busy["id"]], status="in_progress")
    new_task(client, h(client, code), content="Later", lead_worker_id=assigned["id"])  # 未开始也算忙碌
    d = client.get("/api/duty", headers=h(client, code)).json()
    team = next(x for x in d["teams"] if x["team_id"] == main)
    st = {x["worker"]["name"]: x for x in team["workers"]}
    assert st["Duty Busy"]["status"] == "busy" and st["Duty Busy"]["tasks"][0]["content"]["en"] == "Busy work"
    assert st["Duty Idle"]["status"] == "idle" and st["Duty Leave"]["status"] == "leave"
    assert st["Duty Assigned"]["status"] == "busy" and st["Duty Assigned"]["tasks"][0]["is_lead"]
    assert d["counts"]["busy"] >= 1 and d["counts"]["absent"] >= 1 and d["can_add"] is True
    # 管理人员单独数；班长、副班长（首页单独显示）照常算在岗
    c, on = d["counts"], ("busy", "idle")
    assert c["managers"] == sum(1 for x in d["managers"] if x["status"] in on)
    assert c["on_duty"] == sum(1 for x in [*d["top"], *(y for t in d["teams"] for y in t["workers"])]
                               if x["status"] in on) == c["busy"] + c["idle"]
    # 不在这个班次的班长不能快捷添加
    other = next(c for c in ("T1", "T2", "T3", "T4") if teams[c] not in [x["team_id"] for x in d["teams"]])
    assert client.get("/api/duty", headers=h(client, other)).json()["can_add"] is False
    nxt = client.get("/api/duty", headers=admin_h, params={"which": "next"}).json()
    assert (nxt["shift_date"], nxt["shift_kind"]) != (d["shift_date"], d["shift_kind"])


def test_avatar(client, admin_h, teams):
    w = client.post("/api/workers", headers=admin_h, json={"name": "Avatar Guy", "team_id": teams["T2"]}).json()
    assert w["avatar_url"] is None
    img = Image.new("RGB", (800, 400), (10, 120, 200))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    up = lambda hdr: client.post(f"/api/workers/{w['id']}/avatar", headers=hdr,
                                 files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")})
    assert up(h(client, "T1")).status_code == 403  # 别的班组班长不能改
    r = up(h(client, "T2")).json()
    assert r["avatar_url"].startswith(f"/api/workers/{w['id']}/avatar?v=")
    got = client.get(r["avatar_url"])
    assert got.status_code == 200 and Image.open(io.BytesIO(got.content)).size == (256, 256)
    assert client.get(r["avatar_url"].split("&t=")[0] + "&t=bad").status_code == 404
    lst = {x["id"]: x for x in client.get("/api/workers", headers=admin_h).json()}
    assert lst[w["id"]]["avatar_url"]
    assert client.delete(f"/api/workers/{w['id']}/avatar", headers=admin_h).json()["avatar_url"] is None
    assert client.post(f"/api/workers/{w['id']}/avatar", headers=admin_h,
                       files={"file": ("x.jpg", b"nope", "image/jpeg")}).status_code == 400


def test_board_done_this_shift(client, admin_h):
    """本班完成：在班的班组 = 本班次开始以来完成的；不在班 = 它上一个班完成的。"""
    b = client.get("/api/board", headers=admin_h).json()  # 管理员默认看在班班组
    assert b["on_duty"] and (b["done_shift_date"], b["done_shift_kind"]) == (b["shift_date"], b["shift_kind"])
    t = new_task(client, admin_h, content="Done now", status="done", team_id=b["team_id"])
    b = client.get("/api/board", headers=admin_h).json()
    assert t["id"] in [x["id"] for x in b["done_recent"]]
    for tid in {x["id"] for x in client.get("/api/teams", headers=admin_h).json()}:
        bo = client.get("/api/board", headers=admin_h, params={"team_id": tid}).json()
        if not bo["on_duty"]:  # 不在班：显示的是更早的班次，不含刚完成的任务
            assert bo["done_shift_date"] <= b["shift_date"]
            assert t["id"] not in [x["id"] for x in bo["done_recent"]]


def test_duty_managers(client, admin_h):
    """管理人员 = 能给整个车间派活的人（新建任务范围本车间 / 全厂）。按个人排班算在不在班，单独一块，不在班组里；
    没设排班的列出来提醒。"""
    d = client.get("/api/duty", headers=admin_h).json()
    day, kind = d["shift_date"], d["shift_kind"]
    rid = next(r["id"] for r in client.get("/api/roles", headers=admin_h).json() if r["code"] == "dept_admin")

    def mk(name, pattern):
        w = client.post("/api/workers", headers=admin_h, json={"name": name}).json()
        assert client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"role_id": rid}).status_code == 200
        if pattern:
            r = client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json={
                "effective_from": day, "team_id": None, "personal": True, "pattern": pattern, "cycle_start": day})
            assert r.status_code == 200, r.text
        return w

    mk("Mgr On", [kind])
    mk("Mgr Off", ["night" if kind == "day" else "day"])  # 上别的班
    mk("Mgr Nosched", None)
    d = client.get("/api/duty", headers=admin_h).json()
    names = [x["worker"]["name"] for x in d["managers"]]
    assert "Mgr On" in names and "Mgr Off" not in names
    assert "Mgr Nosched" in d["managers_unscheduled"]
    assert d["counts"]["managers"] >= 1
    assert all(y["worker"]["name"] != "Mgr On" for t in d["teams"] for y in t["workers"])
