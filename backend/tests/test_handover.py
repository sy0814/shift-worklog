import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db import SessionLocal
from app.models import Task

from .conftest import login


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


@pytest.fixture(scope="module")
def t2_h(client):
    return login(client, "t2_leader1", "t2_leader1")


def new_task(client, h, **kw):
    body = {"client_id": str(uuid.uuid4()), "content": "Pregled pumpe 4", "lang": "sr"} | kw
    r = client.post("/api/tasks", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_default_target(client, leader_h, teams):
    r = client.get("/api/handover/default", headers=leader_h, params={"team_id": teams["T1"]}).json()
    assert r["to_team_id"] in teams.values() and r["to_team_id"] != teams["T1"]


def test_handover_flow(client, leader_h, t2_h, teams):
    t = new_task(client, leader_h, leftover="Nedostaje zaptivka", status="in_progress")
    # 加一张图
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buf, "JPEG")
    client.post(f"/api/tasks/{t['id']}/attachments", headers=leader_h,
                files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")}, data={"client_id": str(uuid.uuid4())})

    # 2 班不能移交 1 班的任务
    r = client.post("/api/handover", headers=t2_h, json={"task_ids": [t["id"]], "to_team_id": teams["T3"]})
    assert r.status_code == 403
    # 不能交给自己
    r = client.post("/api/handover", headers=leader_h, json={"task_ids": [t["id"]], "to_team_id": teams["T1"]})
    assert r.status_code == 400

    r = client.post("/api/handover", headers=leader_h,
                    json={"task_ids": [t["id"]], "to_team_id": teams["T2"], "note": "等备件到货再装", "lang": "zh"})
    assert r.status_code == 200, r.text
    new = r.json()[0]
    assert new["team_id"] == teams["T2"] and new["source_task_id"] == t["id"]
    assert new["status"] == "in_progress" and new["handover_count"] == 1
    assert new["content"]["sr"] == "Pregled pumpe 4" and new["source_lang"] == "sr"
    assert new["leftover"]["zh"] == "等备件到货再装" and new["leftover"]["sr"] is None
    assert new["workers"] == [] and len(new["attachments"]) == 1
    assert new["handover_in"]["team_id"] == teams["T1"] and new["handover_in"]["note"] == "等备件到货再装"
    assert new["chain_started_at"] == t["chain_started_at"]
    assert new["can_edit"] is False  # 1 班长看 2 班的任务

    old = client.get(f"/api/tasks/{t['id']}", headers=leader_h).json()
    assert old["status"] == "handed_over" and old["can_edit"] is False
    assert old["handover_out"]["team_id"] == teams["T2"] and old["handover_out"]["task_id"] == new["id"]
    # 已移交的不能再改、再移交
    assert client.patch(f"/api/tasks/{t['id']}", headers=leader_h, json={"content": "x"}).status_code == 409
    assert client.post("/api/handover", headers=leader_h, json={"task_ids": [t["id"]]}).status_code == 409

    # 2 班能处理收到的任务，图片能看
    assert client.post(f"/api/tasks/{new['id']}/status", headers=t2_h, json={"status": "done"}).status_code == 200
    assert client.get(new["attachments"][0]["url_thumb"]).status_code == 200

    hist = client.get(f"/api/tasks/{t['id']}/history", headers=leader_h).json()
    assert "handover" in [h["action"] for h in hist]
    hist2 = client.get(f"/api/tasks/{new['id']}/history", headers=t2_h).json()
    assert hist2[0]["action"] == "receive"


def test_handover_default_and_keep_leftover(client, leader_h, teams):
    t = new_task(client, leader_h, leftover="Proveriti sutra")
    default = client.get("/api/handover/default", headers=leader_h, params={"team_id": teams["T1"]}).json()["to_team_id"]
    new = client.post("/api/handover", headers=leader_h, json={"task_ids": [t["id"]]}).json()[0]
    assert new["team_id"] == default
    assert new["leftover"]["sr"] == "Proveriti sutra"  # 没填说明时沿用原遗留问题
    assert new["handover_in"]["default_team_id"] == default


def test_batch_handover(client, leader_h, teams):
    a, b = new_task(client, leader_h), new_task(client, leader_h)
    r = client.post("/api/handover", headers=leader_h, json={"task_ids": [a["id"], b["id"]], "to_team_id": teams["T4"]})
    assert [t["source_task_id"] for t in r.json()] == [a["id"], b["id"]]
    # 其中一条不能移交 → 整批都不移交
    c, d = new_task(client, leader_h), new_task(client, leader_h, status="done")
    r = client.post("/api/handover", headers=leader_h, json={"task_ids": [c["id"], d["id"]], "to_team_id": teams["T4"]})
    assert r.status_code == 409
    assert client.get(f"/api/tasks/{c['id']}", headers=leader_h).json()["status"] == "not_started"


def test_discard(client, leader_h, t2_h):
    t = new_task(client, leader_h)
    assert client.post(f"/api/tasks/{t['id']}/discard", headers=leader_h, json={"reason": " "}).status_code == 400
    assert client.post(f"/api/tasks/{t['id']}/discard", headers=t2_h, json={"reason": "x"}).status_code == 403
    r = client.post(f"/api/tasks/{t['id']}/discard", headers=leader_h, json={"reason": "设备已报废", "lang": "zh"})
    body = r.json()
    assert body["status"] == "discarded" and body["discard_reason"]["zh"] == "设备已报废"
    assert body["discarded_by_name"] == "t1_leader1" and body["discarded_at"]
    assert client.post(f"/api/tasks/{t['id']}/discard", headers=leader_h, json={"reason": "again"}).status_code == 409
    hist = client.get(f"/api/tasks/{t['id']}/history", headers=leader_h).json()
    assert any(h["action"] == "discard" and h["field"] == "status" for h in hist)


def test_overdue_and_settings(client, admin_h, leader_h, teams):
    t = new_task(client, leader_h)
    assert t["overdue"] is False
    # 把第一次录入时间改到 30 小时前
    with SessionLocal() as db:
        db.get(Task, t["id"]).chain_started_at = datetime.now(timezone.utc) - timedelta(hours=30)
        db.commit()
    got = client.get(f"/api/tasks/{t['id']}", headers=leader_h).json()
    assert got["overdue"] is True and got["age_hours"] >= 30
    ids = [x["id"] for x in client.get("/api/overdue", headers=leader_h).json()]
    assert t["id"] in ids
    assert t["id"] in [x["id"] for x in client.get("/api/tasks", headers=leader_h, params={"overdue": True}).json()["items"]]

    assert client.put("/api/settings", headers=leader_h, json={"overdue_hours": 48, "overdue_handovers": 3}).status_code == 403
    assert client.put("/api/settings", headers=admin_h, json={"overdue_hours": 48, "overdue_handovers": 3}).json()["overdue_hours"] == 48
    assert client.get(f"/api/tasks/{t['id']}", headers=leader_h).json()["overdue"] is False
    # 移交次数达到阈值
    client.put("/api/settings", headers=admin_h, json={"overdue_hours": 48, "overdue_handovers": 1})
    moved = client.post("/api/handover", headers=leader_h, json={"task_ids": [t["id"]], "to_team_id": teams["T2"]}).json()[0]
    assert moved["overdue"] is True
    client.put("/api/settings", headers=admin_h, json={"overdue_hours": 24, "overdue_handovers": 3})
    logs = client.get("/api/audit", headers=admin_h, params={"entity": "setting"}).json()["items"]
    assert {l["field"] for l in logs} == {"overdue_hours", "overdue_handovers"}


def test_board(client, leader_h, t2_h, teams):
    mine = new_task(client, leader_h, content="Board todo")
    passed = new_task(client, leader_h, content="Board pass")
    got = client.post("/api/handover", headers=leader_h, json={"task_ids": [passed["id"]], "to_team_id": teams["T2"]}).json()[0]
    b1 = client.get("/api/board", headers=leader_h, params={"team_id": teams["T1"]}).json()
    assert mine["id"] in [t["id"] for t in b1["todo"]]
    assert "handed_out_recent" not in b1  # 已去掉「最近 12 小时移交出去」
    assert b1["next_team_id"] and b1["shift_kind"] in ("day", "middle", "night")
    b2 = client.get("/api/board", headers=t2_h, params={"team_id": teams["T2"]}).json()
    assert got["id"] in [t["id"] for t in b2["received"]]
    assert got["id"] not in [t["id"] for t in b2["todo"]]
    # 超时的排在最前
    assert [t["overdue"] for t in b2["received"]] == sorted([t["overdue"] for t in b2["received"]], reverse=True)
