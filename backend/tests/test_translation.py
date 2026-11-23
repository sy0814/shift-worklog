"""翻译流程测试：用 httpx.MockTransport 模拟 DeepSeek 接口。"""

import io
import json
import re
import uuid

import httpx
import pytest

from app import translation_service, translator
from app.config import get_settings
from app.db import SessionLocal
from app.models import Task

from .conftest import login


class FakeDeepSeek:
    """按规则「翻译」：给每种语言加前缀，便于断言。"""

    def __init__(self):
        self.calls: list[dict] = []
        self.mode = "ok"  # ok / 500 / 400 / timeout / badjson / cyrillic
        self.on_call = None

    @staticmethod
    def detect(text: str) -> str:
        if re.search(r"[一-鿿]", text):
            return "zh"
        if re.search(r"[čćšžđČĆŠŽĐ]|\b(je|na|i|traka|pumpe|ulja|zameniti)\b", text, re.I):
            return "sr"
        return "en"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        if self.on_call:
            self.on_call(body)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if self.mode == "500":
            return httpx.Response(500, text="server error")
        if self.mode == "400":
            return httpx.Response(400, text="bad request")
        text = body["messages"][-1]["content"]
        src = self.detect(text)
        out = {"source_lang": src, "zh": f"[zh]{text}", "sr": f"[sr]{text}", "en": f"[en]{text}"}
        out[src] = "MODEL COPY (should be replaced by original)"
        if self.mode == "cyrillic":
            out["sr"] = "Проверити пумпу"
        content = "not json" if self.mode == "badjson" else json.dumps(out, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def fake(monkeypatch):
    f = FakeDeepSeek()
    s = get_settings()
    monkeypatch.setattr(s, "deepseek_api_key", "test-key")
    monkeypatch.setattr(translator.time, "sleep", lambda _: None)
    monkeypatch.setattr(translation_service, "client_factory",
                        lambda: httpx.Client(transport=httpx.MockTransport(f)))
    return f


def new_task(client, h, **kw):
    body = {"client_id": str(uuid.uuid4()), "content": "检查 3# 球磨机润滑油压", "lang": "zh"} | kw
    r = client.post("/api/tasks", headers=h, json=body)
    assert r.status_code == 201, r.text
    return client.get(f"/api/tasks/{r.json()['id']}", headers=h).json()  # 后台翻译已在响应后执行


def test_request_format(client, leader_h, fake):
    t = new_task(client, leader_h)
    req = fake.calls[0]
    assert req["model"] == get_settings().deepseek_model
    assert req["response_format"] == {"type": "json_object"}
    assert req["thinking"] == {"type": "disabled"}
    assert req["messages"][0]["role"] == "system" and "JSON" in req["messages"][0]["content"]
    assert "球磨机 | mlin sa kuglama | ball mill" in req["messages"][0]["content"]  # 术语表
    assert req["messages"][-1] == {"role": "user", "content": "检查 3# 球磨机润滑油压"}
    assert t["translation_status"] == "done"
    assert t["content"] == {"zh": "检查 3# 球磨机润滑油压", "sr": "[sr]检查 3# 球磨机润滑油压",
                            "en": "[en]检查 3# 球磨机润滑油压"}


def test_system_prompt_is_stable_prefix(client, leader_h, fake):
    new_task(client, leader_h, content="A")
    new_task(client, leader_h, content="B")
    assert fake.calls[0]["messages"][0] == fake.calls[1]["messages"][0]  # 系统提示词完全相同 → 可命中缓存


def test_detects_source_language(client, leader_h, fake):
    # 中文界面里输入了塞语
    t = new_task(client, leader_h, content="Zameniti ležaj pumpe 4", lang="zh", leftover="Fali zaptivka")
    assert t["source_lang"] == "sr" and t["content"]["sr"] == "Zameniti ležaj pumpe 4"
    assert t["content"]["zh"] == "[zh]Zameniti ležaj pumpe 4"
    assert t["leftover_source_lang"] == "en" or t["leftover"]["sr"]  # 各段独立判断
    hist = client.get(f"/api/tasks/{t['id']}/history", headers=leader_h).json()
    assert any(h["action"] == "translate" and h["user_id"] is None for h in hist)
    # 离线重试：原文已挪到 sr 列，同一 client_id 重新提交仍然认得
    r = client.post("/api/tasks", headers=leader_h,
                    json={"client_id": t["client_id"], "content": "Zameniti ležaj pumpe 4", "lang": "zh"})
    assert r.status_code == 201 and r.json()["id"] == t["id"]


def test_serbian_forced_latin(client, leader_h, fake):
    fake.mode = "cyrillic"
    t = new_task(client, leader_h, content="Check pump")
    assert t["content"]["sr"] == "Proveriti pumpu"


def test_failure_then_background_retry(client, leader_h, fake):
    fake.mode = "500"
    t = new_task(client, leader_h, content="Inspect belt 5", lang="en")
    assert len(fake.calls) == get_settings().translate_retries + 1
    assert t["translation_status"] == "pending" and t["content"]["en"] == "Inspect belt 5"
    with SessionLocal() as db:
        task = db.get(Task, t["id"])
        assert task.translation_attempts == 1 and "500" in task.translation_error
    fake.mode = "ok"
    assert translation_service.retry_pending() >= 1
    t = client.get(f"/api/tasks/{t['id']}", headers=leader_h).json()
    assert t["translation_status"] == "done" and t["content"]["zh"] == "[zh]Inspect belt 5"


def test_timeout_and_bad_json_retry(client, leader_h, fake):
    fake.mode = "timeout"
    t = new_task(client, leader_h, content="Timeout case")
    assert t["translation_status"] == "pending"
    fake.calls.clear()
    fake.mode = "badjson"
    translation_service.translate_task(t["id"])
    assert len(fake.calls) == get_settings().translate_retries + 1


def test_client_error_not_retried(client, leader_h, fake):
    fake.mode = "400"
    new_task(client, leader_h, content="Bad request case")
    assert len(fake.calls) == 1


def test_gives_up_after_max_attempts(client, leader_h, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "translate_max_attempts", 2)
    fake.mode = "500"
    t = new_task(client, leader_h, content="Give up case")
    translation_service.translate_task(t["id"])
    assert client.get(f"/api/tasks/{t['id']}", headers=leader_h).json()["translation_status"] == "failed"


def test_admin_retry_failed(client, admin_h, leader_h, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "translate_max_attempts", 1)
    fake.mode = "500"
    t = new_task(client, leader_h, content="Retry failed case")
    assert t["translation_status"] == "failed"
    st = client.get("/api/translation/status", headers=admin_h).json()
    assert st["configured"] and st["counts"]["failed"] >= 1
    fake.mode = "ok"
    assert client.post("/api/translation/retry-failed", headers=admin_h).json()["reset"] >= 1
    assert client.get(f"/api/tasks/{t['id']}", headers=leader_h).json()["translation_status"] == "done"


def test_no_key_stays_pending(client, leader_h):
    t = new_task(client, leader_h, content="No key")
    assert t["translation_status"] == "pending" and t["content"]["zh"] == "No key"


def test_manual_correction_and_edit(client, leader_h, fake):
    t = new_task(client, leader_h, content="Proveriti nivo ulja", lang="sr")
    tid = t["id"]
    put = lambda **kw: client.put(f"/api/tasks/{tid}/translation", headers=leader_h, json=kw)
    assert put(field="content", lang="sr", text="x").status_code == 400  # 原文要走编辑
    r = put(field="content", lang="zh", text="检查油位")
    assert r.json()["content"]["zh"] == "检查油位" and r.json()["manual_fields"] == ["content_zh"]
    assert put(field="content", lang="en", text="Check oil level").json()["content"]["en"] == "Check oil level"

    # 改原文但保留人工译文
    fake.calls.clear()
    r = client.patch(f"/api/tasks/{tid}", headers=leader_h,
                     json={"content": "Proveriti nivo ulja u reduktoru", "lang": "sr", "retranslate": False}).json()
    assert r["content"]["zh"] == "检查油位" and r["manual_fields"] == ["content_zh", "content_en"]
    assert fake.calls == []
    # 改原文并重新翻译 → 人工译文被替换
    r = client.patch(f"/api/tasks/{tid}", headers=leader_h,
                     json={"content": "Proveriti nivo ulja u reduktoru 2", "lang": "sr"}).json()
    r = client.get(f"/api/tasks/{tid}", headers=leader_h).json()
    assert r["manual_fields"] == [] and r["content"]["zh"] == "[zh]Proveriti nivo ulja u reduktoru 2"


def test_machine_translation_keeps_manual(client, leader_h, fake):
    t = new_task(client, leader_h, content="Check idler", lang="en")
    r = client.put(f"/api/tasks/{t['id']}/translation", headers=leader_h,
                   json={"field": "content", "lang": "sr", "text": "Проверити ваљак"})
    assert r.json()["content"]["sr"] == "Proveriti valjak"  # 人工输入的西里尔也转拉丁
    r = client.post(f"/api/tasks/{t['id']}/retranslate", headers=leader_h).json()
    assert r["content"]["sr"] == "Proveriti valjak" and r["content"]["zh"] == "[zh]Check idler"
    r = client.post(f"/api/tasks/{t['id']}/retranslate", headers=leader_h, params={"keep_manual": False}).json()
    assert r["content"]["sr"] == "[sr]Check idler" and r["manual_fields"] == []


def test_stale_result_discarded(client, leader_h, fake):
    """翻译期间原文被改了 → 这次结果作废。"""
    t = new_task(client, leader_h, content="Original text", lang="en")
    with SessionLocal() as db:
        task = db.get(Task, t["id"])
        task.content_zh = task.content_sr = None
        task.translation_status = "pending"
        db.commit()

    def edit_during_call(_):
        with SessionLocal() as db:
            db.get(Task, t["id"]).content_en = "Edited meanwhile"
            db.commit()
    fake.on_call = edit_during_call
    translation_service.translate_task(t["id"])
    with SessionLocal() as db:
        task = db.get(Task, t["id"])
        assert task.content_zh is None and task.translation_status == "pending"


def test_leftover_discard_and_handover_translated(client, leader_h, fake):
    teams = {x["code"]: x["id"] for x in client.get("/api/teams", headers=leader_h).json()}
    t = new_task(client, leader_h, content="Pump 4 inspection", lang="en")
    new = client.post("/api/handover", headers=leader_h,
                      json={"task_ids": [t["id"]], "to_team_id": teams["T2"], "note": "等备件", "lang": "zh"}).json()[0]
    new = client.get(f"/api/tasks/{new['id']}", headers=login(client, "t2_leader1", "t2_leader1")).json()
    assert new["leftover"] == {"zh": "等备件", "sr": "[sr]等备件", "en": "[en]等备件"}
    assert new["content"]["zh"] == "[zh]Pump 4 inspection"  # 译文随移交带过去

    d = new_task(client, leader_h, content="Old task", lang="en")
    client.post(f"/api/tasks/{d['id']}/discard", headers=leader_h, json={"reason": "设备已拆除", "lang": "zh"})
    d = client.get(f"/api/tasks/{d['id']}", headers=leader_h).json()
    assert d["discard_reason"]["en"] == "[en]设备已拆除" and d["translation_status"] == "done"


# ---------------- 术语表 ----------------
def test_glossary_seeded(client, leader_h):
    g = client.get("/api/glossary", headers=leader_h).json()
    assert len(g) == 51
    assert any(x["zh"] == "球磨机" and x["sr"] == "mlin sa kuglama" for x in g)


def test_glossary_crud_and_permissions(client, admin_h, leader_h):
    body = {"zh": "补偿器", "sr": "Компензатор", "en": "expansion joint", "category": "机械"}
    assert client.post("/api/glossary", headers=leader_h, json=body).status_code == 403
    r = client.post("/api/glossary", headers=admin_h, json=body)
    assert r.status_code == 201 and r.json()["sr"] == "Kompenzator"
    assert client.post("/api/glossary", headers=admin_h, json=body).status_code == 409
    tid = r.json()["id"]
    r = client.put(f"/api/glossary/{tid}", headers=admin_h, json=body | {"en": "compensator"})
    assert r.json()["en"] == "compensator"
    assert client.delete(f"/api/glossary/{tid}", headers=admin_h).status_code == 204
    logs = client.get("/api/audit", headers=admin_h, params={"entity": "glossary", "entity_id": str(tid)}).json()["items"]
    assert [l["action"] for l in logs] == ["delete", "update", "create"]


def test_glossary_import_export(client, admin_h, leader_h):
    csv_text = "﻿zh,sr,en,category,note\n球磨机,kuglični mlin,ball mill,磨矿,已校对\n新词,nova reč,new term,通用,\n坏行,,x,,\n"
    r = client.post("/api/glossary/import", headers=admin_h,
                    files={"file": ("g.csv", io.BytesIO(csv_text.encode()), "text/csv")}).json()
    assert r == {"added": 1, "updated": 1, "skipped": 1}
    g = {x["zh"]: x for x in client.get("/api/glossary", headers=leader_h).json()}
    assert g["球磨机"]["sr"] == "kuglični mlin" and g["球磨机"]["note"] == "已校对"
    exp = client.get("/api/glossary/export", headers=leader_h)
    assert exp.text.startswith("﻿zh,sr,en,category,note") and "kuglični mlin" in exp.text


def test_queue_under_burst(client, leader_h, fake, monkeypatch):
    """一波并发录入：请求立即返回，同时最多 WORKERS 个翻译调用，最后全部翻译完。"""
    import threading
    import time as _t
    from concurrent.futures import ThreadPoolExecutor

    active, peak, lock = [0], [0], threading.Lock()

    def slow(_body):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        _t.sleep(0.15)
        with lock:
            active[0] -= 1
    fake.on_call = slow
    translation_service.start_workers()
    try:
        def create(i):
            t0 = _t.monotonic()
            r = client.post("/api/tasks", headers=leader_h,
                            json={"client_id": str(uuid.uuid4()), "content": f"Burst task {i}", "lang": "en"})
            assert r.status_code == 201
            return r.json()["id"], _t.monotonic() - t0
        with ThreadPoolExecutor(6) as ex:
            results = list(ex.map(create, range(30)))
        assert max(d for _, d in results) < 1.0  # 请求不等翻译
        deadline = _t.monotonic() + 30
        ids = [i for i, _ in results]
        while _t.monotonic() < deadline:
            sts = [client.get(f"/api/tasks/{i}", headers=leader_h).json()["translation_status"] for i in ids]
            if all(s == "done" for s in sts):
                break
            _t.sleep(0.2)
        assert all(s == "done" for s in sts)
        assert peak[0] <= translation_service.WORKERS
    finally:
        translation_service.stop_workers()
