"""任务的班次日志：多条自由填写的记录、自动翻译、按写的时间归班次、移交后下一班能看到、离线去重、删除。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.schedule_service import load_schedule

from .conftest import login
from .test_translation import fake  # noqa: F401  假 DeepSeek


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def new_task(client, h, **kw):
    body = {"client_id": str(uuid.uuid4()), "content": "检查 2# 浮选机", "lang": "zh"} | kw
    r = client.post("/api/tasks", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def add(client, h, task_id, text, lang="zh", **kw):
    return client.post(f"/api/tasks/{task_id}/logs", headers=h, json={"content": text, "lang": lang} | kw)


def test_add_translate_list(client, leader_h, fake):  # noqa: F811
    t = new_task(client, leader_h)
    assert t["perms"]["log"] is True
    r = add(client, leader_h, t["id"], "  电机温度 75℃，偏高，已通知电工  ")
    assert r.status_code == 201, r.text
    x = r.json()
    # 当场翻译（测试里没有后台线程）：原文原样保留，另外两种是译文
    logs = client.get(f"/api/tasks/{t['id']}/logs", headers=leader_h).json()
    assert len(logs) == 1
    c = logs[0]["content"]
    assert c["zh"] == "电机温度 75℃，偏高，已通知电工" and c["sr"].startswith("[sr]") and c["en"].startswith("[en]")
    assert logs[0]["translation_status"] == "done" and logs[0]["author"] and logs[0]["can_delete"]
    # 班次按写的时间算
    now = datetime.now(get_settings().tz).replace(tzinfo=None)
    with SessionLocal() as db:
        d, k = load_schedule(db).shift_at(now)
    assert (x["shift_date"], x["shift_kind"]) == (str(d), k)
    # 留痕
    hist = client.get(f"/api/tasks/{t['id']}/history", headers=leader_h).json()
    assert any(h["action"] == "log" for h in hist)


def test_serbian_cyrillic_to_latin(client, leader_h):
    t = new_task(client, leader_h)
    x = add(client, leader_h, t["id"], "Пумпа ради", lang="sr").json()
    assert x["content"]["sr"] == "Pumpa radi"


def test_offline_dedupe_and_recorded_at(client, leader_h):
    t = new_task(client, leader_h)
    cid = str(uuid.uuid4())
    at = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    a = add(client, leader_h, t["id"], "离线写的", client_id=cid, recorded_at=at)
    assert a.status_code == 201
    b = add(client, leader_h, t["id"], "离线写的", client_id=cid, recorded_at=at)  # 联网后重发
    assert b.status_code == 201 and b.json()["id"] == a.json()["id"]
    assert len(client.get(f"/api/tasks/{t['id']}/logs", headers=leader_h).json()) == 1
    assert add(client, leader_h, t["id"], "别的内容", client_id=cid).status_code == 409
    # 写的时间 5 小时前：班次按 5 小时前算；太早的按 3 天前算
    local = (datetime.fromisoformat(at).astimezone(get_settings().tz)).replace(tzinfo=None)
    with SessionLocal() as db:
        d, k = load_schedule(db).shift_at(local)
    assert (a.json()["shift_date"], a.json()["shift_kind"]) == (str(d), k)
    old = add(client, leader_h, t["id"], "很久以前", recorded_at="2020-01-01T00:00:00Z").json()
    assert datetime.fromisoformat(old["recorded_at"]) > datetime.now(timezone.utc) - timedelta(days=3, minutes=1)


def test_chain_after_handover(client, leader_h, teams):
    t = new_task(client, leader_h)
    add(client, leader_h, t["id"], "1 班：已拆开检查，缺一个密封圈")
    new = client.post("/api/handover", headers=leader_h, json={"task_ids": [t["id"]], "to_team_id": teams["T2"]}).json()[0]
    # 原任务已移交：不能再写
    assert add(client, leader_h, t["id"], "补一句").status_code == 409
    t2_h = login(client, "t2_leader1", "t2_leader1")
    assert add(client, t2_h, new["id"], "2 班：密封圈已换好").status_code == 201
    logs = client.get(f"/api/tasks/{new['id']}/logs", headers=t2_h).json()
    assert [x["content"]["zh"] for x in logs] == ["1 班：已拆开检查，缺一个密封圈", "2 班：密封圈已换好"]
    assert [x["task_id"] for x in logs] == [t["id"], new["id"]]
    # 前一班写的，接班的人不能删（原任务已移交）
    assert logs[0]["can_delete"] is False


def test_permissions_and_delete(client, leader_h, admin_h, teams):
    t = new_task(client, leader_h)
    x = add(client, leader_h, t["id"], "要删的").json()
    t3_h = login(client, "t3_leader1", "t3_leader1")  # 别的班组
    assert add(client, t3_h, t["id"], "不是我的班组").status_code == 403
    assert client.delete(f"/api/task-logs/{x['id']}", headers=t3_h).status_code == 403
    assert client.delete(f"/api/task-logs/{x['id']}", headers=leader_h).status_code == 204
    assert client.get(f"/api/tasks/{t['id']}/logs", headers=leader_h).json() == []
    assert client.delete(f"/api/task-logs/{x['id']}", headers=leader_h).status_code == 404
    hist = client.get(f"/api/tasks/{t['id']}/history", headers=leader_h).json()
    assert any(h["action"] == "log_delete" for h in hist)
    # 已完成的任务：班长不能再写（和改已完成的任务一样），管理员可以
    done = new_task(client, leader_h, status="done")
    assert add(client, leader_h, done["id"], "完成后补充").status_code == 403
    assert add(client, admin_h, done["id"], "管理员补充").status_code == 201
