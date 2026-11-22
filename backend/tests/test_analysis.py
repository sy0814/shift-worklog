import json
import uuid

import httpx
import pytest

from app import analysis, translation_service
from app.config import get_settings

from .conftest import login


class FakeLLM:
    def __init__(self):
        self.bodies = []
        self.status = 200

    def __call__(self, request):
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.status != 200:
            return httpx.Response(self.status, text="boom")
        return httpx.Response(200, json={"choices": [{"message": {"content": "## 1. Summary\n- ok"}}],
                                         "usage": {"prompt_tokens": 1200, "completion_tokens": 300}})


@pytest.fixture
def llm(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-key")
    monkeypatch.setattr(translation_service, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(f)))
    monkeypatch.setattr(analysis, "start_in_background", analysis.run_report)  # 测试里同步执行
    monkeypatch.setattr(analysis.time, "sleep", lambda _: None)
    return f


@pytest.fixture(scope="module")
def data(client, admin_h):
    """3 班：两个人，其中一人做了 2 条有工时的任务，另一人 0 条；还有一条没人参与的任务。"""
    teams = {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}
    ws = client.post("/api/workers/bulk", headers=admin_h, json={"names": ["An Busy", "An Idle"], "team_id": teams["T3"]}).json()
    h3 = login(client, "t3_leader1", "t3_leader1")
    mk = lambda **kw: client.post("/api/tasks", headers=h3, json={"client_id": str(uuid.uuid4()), "lang": "en",
                                                                 "recorded_at": "2026-11-21T10:00:00+01:00"} | kw).json()
    mk(content="Replace idler", worker_ids=[ws[0]["id"]], status="done",
       start_at="2026-11-21T08:00:00+01:00", end_at="2026-11-21T11:00:00+01:00")
    mk(content="Check pump seal", worker_ids=[ws[0]["id"]], status="done",
       start_at="2026-11-21T11:00:00+01:00", end_at="2026-11-21T12:30:00+01:00")
    mk(content="Clean thickener launder")
    return {"team": teams["T3"], "busy": ws[0]["name"], "idle": ws[1]["name"]}


def test_permissions(client, leader_h):
    assert client.get("/api/analysis", headers=leader_h).status_code == 403
    assert client.post("/api/analysis", headers=leader_h, json={"start": "2026-11-01", "end": "2026-11-30"}).status_code == 403


def test_report_flow(client, admin_h, llm, data):
    r = client.post("/api/analysis", headers=admin_h,
                    json={"start": "2026-11-01", "end": "2026-11-30", "team_id": data["team"], "lang": "sr"})
    assert r.status_code == 201
    rep = client.get(f"/api/analysis/{r.json()['id']}", headers=admin_h).json()
    assert rep["status"] == "done" and rep["report_md"].startswith("## 1.")
    assert rep["usage"] == {"prompt_tokens": 1200, "completion_tokens": 300}
    # 统计由程序算
    people = {p["name"]: p for p in rep["stats"]["people"]}
    busy, idle = people[data["busy"]], people[data["idle"]]
    assert busy["tasks"] == 2 and busy["done"] == 2 and busy["task_hours"] == 4.5
    assert busy["present_shifts"] == busy["scheduled_shifts"] == 24  # 3 班 11 月：3 个完整循环 18 天 + 余下 6 天（位置 0~5）都上班
    assert busy["hours_per_present_shift"] == round(4.5 / 24, 2)
    assert idle["tasks"] == 0 and idle["task_hours"] == 0
    team = rep["stats"]["teams"][0]
    assert team["tasks"] >= 3 and team["tasks_without_workers"] >= 1
    assert data["idle"] in team["members_present_but_no_tasks"]
    # 发给模型的请求：分析模型、不带关闭思考参数、塞语、统计 JSON
    body = llm.bodies[-1]
    assert body["model"] == "deepseek-v4-pro" and "thinking" not in body
    assert "srpski" in body["messages"][0]["content"]
    sent = json.loads(body["messages"][1]["content"].split("\n", 1)[1])
    assert sent["people"] == rep["stats"]["people"]
    assert client.get("/api/analysis", headers=admin_h).json()[0]["id"] == rep["id"]


def test_failure_and_retry(client, admin_h, llm, data):
    llm.status = 401
    r = client.post("/api/analysis", headers=admin_h, json={"start": "2026-11-01", "end": "2026-11-30"}).json()
    rep = client.get(f"/api/analysis/{r['id']}", headers=admin_h).json()
    assert rep["status"] == "failed" and "401" in rep["error"]
    assert len(llm.bodies) == 1  # 4xx 不重试
    llm.status = 200
    assert client.post(f"/api/analysis/{r['id']}/retry", headers=admin_h).status_code == 200
    assert client.get(f"/api/analysis/{r['id']}", headers=admin_h).json()["status"] == "done"
    assert client.post(f"/api/analysis/{r['id']}/retry", headers=admin_h).status_code == 409


def test_server_error_retried_once(client, admin_h, llm, data):
    llm.status = 503
    r = client.post("/api/analysis", headers=admin_h, json={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert client.get(f"/api/analysis/{r['id']}", headers=admin_h).json()["status"] == "failed"
    assert len(llm.bodies) == 2


def test_empty_period_and_validation(client, admin_h, llm):
    r = client.post("/api/analysis", headers=admin_h, json={"start": "2025-01-01", "end": "2025-01-31"}).json()
    rep = client.get(f"/api/analysis/{r['id']}", headers=admin_h).json()
    assert rep["status"] == "failed" and "no tasks" in rep["error"] and llm.bodies == []
    assert client.post("/api/analysis", headers=admin_h, json={"start": "2026-01-01", "end": "2026-06-01"}).status_code == 400


def test_not_configured(client, admin_h):
    assert client.post("/api/analysis", headers=admin_h, json={"start": "2026-11-01", "end": "2026-11-30"}).status_code == 503
