import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app import inspection_service, translation_service
from app.config import get_settings
from app.db import SessionLocal
from app.models import InspectionRun, InspectionTemplate, Task


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def _mk(client, h, **kw):
    body = {"name": "球磨机巡检", "content": "巡检 1# 球磨机：油温、振动、异响", "lang": "zh", "kind": "daily",
            "at_time": "08:00", "start_date": "2026-11-01"} | kw
    return client.post("/api/inspections", headers=h, json=body)


def _force_due(iid, when):
    with SessionLocal() as db:
        db.get(InspectionTemplate, iid).next_run_at = when
        db.commit()


def test_permissions_and_validation(client, admin_h, leader_h, teams):
    assert _mk(client, leader_h).status_code == 403  # 班长不能建「派给在班班组」的
    assert _mk(client, leader_h, assign="fixed", team_id=teams["T2"]).status_code == 403  # 也不能派给别的班组
    assert client.get("/api/inspections", headers=leader_h).status_code == 200
    assert _mk(client, admin_h, kind="weekly").status_code == 400          # 没选周几
    assert _mk(client, admin_h, kind="monthly", month_days=[32]).status_code == 400
    assert _mk(client, admin_h, kind="shift", shift_kinds=["evening"]).status_code == 400
    assert _mk(client, admin_h, assign="fixed").status_code == 400         # 没选班组


def test_preview(client, admin_h, teams):
    r = client.post("/api/inspections/preview", headers=admin_h, json={
        "name": "x", "content": "x", "kind": "shift", "shift_kinds": ["night"], "assign": "fixed",
        "team_id": teams["T1"], "start_date": "2026-11-01"}).json()
    assert len(r) == 5 and all(o["at"].endswith("23:00:00") and o["team_id"] == teams["T1"] for o in r)
    assert all(o["shift_kind"] == "night" for o in r)


def test_due_creates_task_and_advances(client, admin_h, leader_h, teams):
    t = _mk(client, admin_h).json()
    assert t["next_run_at"] and t["runs"] == 0
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    _force_due(t["id"], past)
    assert inspection_service.run_due() == 1
    assert inspection_service.run_due() == 0  # 再跑一次不重复
    with SessionLocal() as db:
        runs = db.scalars(select(InspectionRun).where(InspectionRun.template_id == t["id"])).all()
        assert [r.status for r in runs] == ["created"]
        task = db.get(Task, runs[0].task_id)
        tpl = db.get(InspectionTemplate, t["id"])
        nxt = tpl.next_run_at if tpl.next_run_at.tzinfo else tpl.next_run_at.replace(tzinfo=timezone.utc)
        assert nxt > datetime.now(timezone.utc)
    got = client.get(f"/api/tasks/{task.id}", headers=leader_h).json()
    assert got["inspection_name"] == "球磨机巡检" and got["content"]["zh"].startswith("巡检 1#")
    assert got["status"] == "not_started"
    hist = client.get(f"/api/tasks/{task.id}/history", headers=admin_h).json()
    assert hist[0]["action"] == "auto_create" and hist[0]["user_id"] is None


def test_catch_up_only_latest(client, admin_h):
    t = _mk(client, admin_h, name="追补测试").json()
    _force_due(t["id"], datetime.now(timezone.utc) - timedelta(days=4, hours=1))  # 错过 5 次左右
    assert inspection_service.run_due() == 1
    with SessionLocal() as db:
        st = [r.status for r in db.scalars(select(InspectionRun).where(InspectionRun.template_id == t["id"])
                                           .order_by(InspectionRun.occurrence_at))]
    assert st[-1] == "created" and set(st[:-1]) == {"skipped"} and len(st) >= 4
    assert client.get(f"/api/inspections/{t['id']}/runs", headers=admin_h).json()[0]["status"] == "created"


def test_duplicate_occurrence_is_not_created_twice(client, admin_h):
    t = _mk(client, admin_h, name="重复测试").json()
    when = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=2)
    _force_due(t["id"], when)
    with SessionLocal() as db:  # 模拟另一个进程已经派过这一次
        db.add(InspectionRun(template_id=t["id"], occurrence_at=when, status="created"))
        db.commit()
    assert inspection_service.run_due() == 0
    with SessionLocal() as db:
        assert db.scalar(select(Task).where(Task.inspection_id == t["id"])) is None


def test_fixed_team_with_workers_and_run_now(client, admin_h, teams):
    w = client.post("/api/workers", headers=admin_h, json={"name": "Insp Worker", "team_id": teams["T4"]}).json()
    t = _mk(client, admin_h, name="4班配电室", assign="fixed", team_id=teams["T4"], worker_ids=[w["id"]],
            kind="weekly", weekdays=[0, 2, 4]).json()
    r = client.post(f"/api/inspections/{t['id']}/run-now", headers=admin_h).json()
    assert r["status"] == "manual" and r["team_id"] == teams["T4"]
    task = client.get(f"/api/tasks/{r['task_id']}", headers=admin_h).json()
    assert task["team_id"] == teams["T4"] and [x["name"] for x in task["workers"]] == ["Insp Worker"]
    assert client.delete(f"/api/inspections/{t['id']}", headers=admin_h).status_code == 409  # 有记录不能删
    body = {k: t[k] for k in ("name", "content", "lang", "kind", "at_time", "every_n", "weekdays", "month_days",
                              "shift_kinds", "start_date", "assign", "team_id", "worker_ids")}
    off = client.put(f"/api/inspections/{t['id']}", headers=admin_h, json=body | {"enabled": False}).json()
    assert off["enabled"] is False and off["next_run_at"] is None
    logs = client.get("/api/audit", headers=admin_h, params={"entity": "inspection", "entity_id": str(t["id"])}).json()["items"]
    assert any(l["field"] == "enabled" for l in logs)


def test_translation_reused(client, admin_h, leader_h, monkeypatch):
    calls = []

    def llm(request):
        body = json.loads(request.content)
        calls.append(body)
        text = body["messages"][-1]["content"]
        out = {"source_lang": "zh", "zh": text, "sr": "Pregled mlina", "en": "Mill inspection"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}]})
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "k")
    monkeypatch.setattr(translation_service, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(llm)))
    t = _mk(client, admin_h, name="翻译复用", content="巡检 2# 球磨机").json()
    a = client.post(f"/api/inspections/{t['id']}/run-now", headers=admin_h).json()
    b = client.post(f"/api/inspections/{t['id']}/run-now", headers=admin_h).json()
    assert len(calls) == 1  # 第二次直接复用译文
    tb = client.get(f"/api/tasks/{b['task_id']}", headers=leader_h).json()
    assert tb["content"]["sr"] == "Pregled mlina" and tb["translation_status"] == "done"
    assert a["task_id"] != b["task_id"]


def test_leader_manages_own_team(client, admin_h, leader_h, teams):
    r = _mk(client, leader_h, name="班长建的", assign="fixed", team_id=teams["T1"])
    assert r.status_code == 201 and r.json()["can_edit"] is True
    iid = r.json()["id"]
    body = {k: r.json()[k] for k in ("name", "content", "lang", "kind", "at_time", "start_date", "assign", "team_id")}
    assert client.put(f"/api/inspections/{iid}", headers=leader_h, json=body | {"at_time": "09:00"}).status_code == 200
    # 不能改成派给别的班组
    assert client.put(f"/api/inspections/{iid}", headers=leader_h, json=body | {"team_id": teams["T2"]}).status_code == 403
    # 管理员建的「在班班组」巡查项：班长能看不能改
    other = _mk(client, admin_h, name="管理员建的").json()
    mine = {x["id"]: x for x in client.get("/api/inspections", headers=leader_h).json()}
    assert mine[other["id"]]["can_edit"] is False and mine[iid]["can_edit"] is True
    assert client.post(f"/api/inspections/{other['id']}/run-now", headers=leader_h).status_code == 403
    assert client.delete(f"/api/inspections/{other['id']}", headers=leader_h).status_code == 403
    assert client.delete(f"/api/inspections/{iid}", headers=leader_h).status_code == 204


def test_yearly(client, admin_h, teams):
    base = {"name": "x", "content": "x", "kind": "yearly", "at_time": "09:00", "start_date": "2026-01-01"}
    assert client.post("/api/inspections/preview", headers=admin_h, json=base).status_code == 400  # 没选日期
    assert client.post("/api/inspections/preview", headers=admin_h, json=base | {"year_dates": ["02-30"]}).status_code == 400
    r = client.post("/api/inspections/preview", headers=admin_h, json=base | {"year_dates": ["3-15", "11-30"]}).json()
    assert [o["at"][:10] for o in r] == ["2026-11-30", "2027-03-15", "2027-11-30", "2028-03-15", "2028-11-30"]
    # 每 2 年一次（从起算日期的年份算），02-29 在平年按 02-28
    r = client.post("/api/inspections/preview", headers=admin_h,
                    json=base | {"year_dates": ["02-29"], "every_n": 2, "start_date": "2027-01-01"}).json()
    assert [o["at"][:10] for o in r][:3] == ["2027-02-28", "2029-02-28", "2031-02-28"]
    t = _mk(client, admin_h, kind="yearly", year_dates=["12-31"]).json()
    assert t["year_dates"] == ["12-31"] and t["next_run_at"].startswith("2026-12-31")


def test_inspection_with_sub_items_creates_project(client, admin_h, leader_h, teams):
    """有小项目的巡查：每次派发生成一个项目，小项目是子项目（没指定就给这次派给的班组）；第二次直接复制译文。"""
    w = client.post("/api/workers", headers=admin_h, json={"name": "Insp Sub W", "team_id": teams["T2"]}).json()
    body = {"name": "每周电气巡检", "content": "", "lang": "zh", "kind": "daily", "at_time": "08:00", "start_date": "2026-11-01",
            "assign": "fixed", "team_id": teams["T1"], "transferable": False,
            "sub_items": [{"content": "1# 变压器油温"}, {"content": "2# 配电柜", "team_id": teams["T3"]},
                          {"content": "电缆沟", "worker_id": w["id"]}]}
    assert _mk(client, admin_h, **(body | {"sub_items": []})).status_code == 400  # 没小项目时内容必填
    # 班长：小项目不能指定别的班组
    assert client.post("/api/inspections", headers=leader_h, json=body).status_code == 403
    t = client.post("/api/inspections", headers=admin_h, json=body).json()
    assert len(t["sub_items"]) == 3 and t["transferable"] is False
    run = client.post(f"/api/inspections/{t['id']}/run-now", headers=admin_h).json()
    assert run["project_id"] and run["task_id"] is None
    p = client.get(f"/api/projects/{run['project_id']}", headers=admin_h).json()
    assert p["name"]["zh"] == "每周电气巡检" and p["total"] == 3 and not p["transferable"] and p["team_id"] == teams["T1"]
    by = {s["content"]["zh"]: s for s in p["subs"]}
    assert by["1# 变压器油温"]["team_id"] == teams["T1"] and by["2# 配电柜"]["team_id"] == teams["T3"]
    assert by["电缆沟"]["lead"]["id"] == w["id"] and by["电缆沟"]["team_id"] == teams["T2"]
    assert all(s["inspection_id"] == t["id"] for s in p["subs"])
    # 第二次派发：上一次已翻译好的直接复制
    with SessionLocal() as db:
        for x in db.scalars(select(Task).where(Task.project_id == run["project_id"])):
            x.content_sr, x.content_en, x.translation_status = "SR " + x.content_zh, "EN " + x.content_zh, "done"
        from app.models import Project
        pr = db.get(Project, run["project_id"])
        pr.name_sr, pr.name_en, pr.translation_status = "Nedeljni", "Weekly", "done"
        db.commit()
    run2 = client.post(f"/api/inspections/{t['id']}/run-now", headers=admin_h).json()
    p2 = client.get(f"/api/projects/{run2['project_id']}", headers=admin_h).json()
    assert p2["name"]["en"] == "Weekly" and all(s["translation_status"] == "done" and s["content"]["en"].startswith("EN ") for s in p2["subs"])
