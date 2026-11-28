"""项目计划开始时间（到「开始时间 - 提前分钟」才出现在待办里）、定期巡查「小项目由当班自己添加」（例如停送电）。
用户 2026-11-28 要的。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import project_service
from app.db import SessionLocal
from app.models import Project, Task
from app.schedule_service import load_schedule, local_now

from .conftest import login


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def board_ids(client, h, team_id):
    b = client.get("/api/board", headers=h, params={"team_id": team_id}).json()
    return {t["id"] for t in b["todo"] + b["received"]}, b


def test_project_with_future_start_hidden_until_lead(client, admin_h, teams):
    now = datetime.now(timezone.utc)
    later = now + timedelta(days=3)
    r = client.post("/api/projects", headers=admin_h, json={
        "name": "周一开始的检修", "lang": "zh", "team_id": teams["T1"], "start_at": iso(later), "lead_minutes": 30,
        "subs": [{"content": "拆护罩", "team_id": teams["T1"]}]})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["start_at"] and p["lead_minutes"] == 30
    sub = p["subs"][0]
    vf = datetime.fromisoformat(sub["visible_from"].replace("Z", "+00:00"))
    assert abs((vf - (later - timedelta(minutes=30))).total_seconds()) < 2
    assert not sub["overdue"]
    # 归属开始时间那个班（不是现在的班）
    with SessionLocal() as db:
        sched = load_schedule(db)
        t1 = sched.team(teams["T1"])
        from app.project_service import to_local
        exp = sched.receiving_slot(t1, to_local(later))
    assert (sub["shift_date"], sub["shift_kind"]) == (str(exp[0]), exp[1])
    # 还没到：本班待办里没有
    ids, _ = board_ids(client, admin_h, teams["T1"])
    assert sub["id"] not in ids
    # 提前时间以内的：马上显示（开始时间 20 分钟后，提前 30 分钟 → 已经该显示）
    soon = client.post("/api/projects", headers=admin_h, json={
        "name": "马上开始", "lang": "zh", "team_id": teams["T1"], "start_at": iso(now + timedelta(minutes=20)),
        "lead_minutes": 30, "subs": [{"content": "接线", "team_id": teams["T1"]}]}).json()
    ids, _ = board_ids(client, admin_h, teams["T1"])
    assert soon["subs"][0]["id"] in ids
    # 改开始时间为空（马上开始）→ 子项目马上显示
    r = client.patch(f"/api/projects/{p['id']}", headers=admin_h, json={"start_at": None})
    assert r.status_code == 200 and r.json()["start_at"] is None and r.json()["subs"][0]["visible_from"] is None
    ids, _ = board_ids(client, admin_h, teams["T1"])
    assert sub["id"] in ids
    # 再改回以后 → 又隐藏；后面加的子项目也按开始时间
    client.patch(f"/api/projects/{p['id']}", headers=admin_h, json={"start_at": iso(later)})
    r = client.post(f"/api/projects/{p['id']}/subs", headers=admin_h, json={"lang": "zh", "subs": [{"content": "换轴承", "team_id": teams["T1"]}]})
    assert all(s["visible_from"] for s in r.json()["subs"])
    ids, _ = board_ids(client, admin_h, teams["T1"])
    assert not ids & {s["id"] for s in r.json()["subs"]}


def test_open_items_inspection(client, admin_h, teams):
    """停送电：定期巡查勾「小项目由当班自己添加」→ 每次派发一个空项目，出现在这个班的交接班里，当班往里加；
    下班后一个都没有 → 自动关闭为「本班无」。"""
    body = {"name": "停送电", "content": "", "lang": "zh", "kind": "shift", "shift_kinds": ["day", "middle", "night"],
            "start_date": "2026-11-01", "assign": "fixed", "team_id": teams["T1"], "open_items": True,
            "sub_items": [{"content": "不该存"}]}
    r = client.post("/api/inspections", headers=admin_h, json=body)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["open_items"] is True and t["sub_items"] == []
    run = client.post(f"/api/inspections/{t['id']}/run-now", headers=admin_h).json()
    pid = run["project_id"]
    p = client.get(f"/api/projects/{pid}", headers=admin_h).json()
    assert p["open_items"] and p["total"] == 0 and p["shift_date"] and p["can_add"]
    # 交接班里有这个项目，班长能往里加
    h1 = login(client, "t1_leader1", "t1_leader1")
    _, b = board_ids(client, h1, teams["T1"])
    card = next((x for x in b["projects"] if x["id"] == pid), None)
    if (p["shift_date"], p["shift_kind"]) == (b["shift_date"], b["shift_kind"]):
        assert card and card["can_add"]
    r = client.post(f"/api/projects/{pid}/subs", headers=h1, json={"lang": "zh", "subs": [{"content": "3# 泵停电"}]})
    assert r.status_code == 200, r.text
    sub = r.json()["subs"][0]
    assert sub["team_id"] == teams["T1"] and (sub["shift_date"], sub["shift_kind"]) == (p["shift_date"], p["shift_kind"])
    # 别的班组的班长不能加
    h3 = login(client, "t3_leader1", "t3_leader1")
    assert client.post(f"/api/projects/{pid}/subs", headers=h3, json={"lang": "zh", "subs": [{"content": "x"}]}).status_code == 403
    # 下班后：空的关闭为「本班无」，有小项目的不动
    run2 = client.post(f"/api/inspections/{t['id']}/run-now", headers=admin_h).json()
    with SessionLocal() as db:
        closed = project_service.close_empty_open_projects(db, local_now() + timedelta(days=2))
        db.commit()
        ids = {x.id for x in closed}
        assert run2["project_id"] in ids and pid not in ids
    p2 = client.get(f"/api/projects/{run2['project_id']}", headers=admin_h).json()
    assert p2["closed_at"] and p2["closed_empty"] and not p2["can_add"]
    assert client.post(f"/api/projects/{run2['project_id']}/subs", headers=admin_h,
                       json={"lang": "zh", "subs": [{"content": "x"}]}).status_code == 403


def test_weekly_inspection_waits_for_start_date(client, admin_h, teams):
    """每周的巡查设了「从哪天开始」：那天之前一次都不派（下一次派发时间在开始日期以后）。"""
    from datetime import date
    start = date.today() + timedelta(days=10)
    r = client.post("/api/inspections", headers=admin_h, json={
        "name": "每周一检查", "content": "检查", "lang": "zh", "kind": "weekly", "weekdays": [0, 1, 2, 3, 4, 5, 6],
        "at_time": "08:00", "start_date": str(start), "assign": "fixed", "team_id": teams["T1"]})
    assert r.status_code == 201, r.text
    nxt = datetime.fromisoformat(r.json()["next_run_at"].replace("Z", "+00:00"))
    assert nxt.date() >= start - timedelta(days=1)  # UTC 可能差几个小时
