import json

import httpx
import pytest
from sqlalchemy import select

from app import llm_config, translation_service, translator
from app.db import SessionLocal
from app.models import AppSetting, AuditLog


class Recorder:
    def __init__(self):
        self.reqs = []
        self.fail = False

    def __call__(self, request: httpx.Request):
        self.reqs.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen-max"}, {"id": "gpt-4o-mini"}]})
        if self.fail:
            return httpx.Response(401, text="invalid key")
        body = json.loads(request.content)
        text = body["messages"][-1]["content"]
        out = {"source_lang": "zh", "zh": text, "sr": "Prevod", "en": "Translation"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}]})


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(translation_service, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(r)))
    monkeypatch.setattr(translator.time, "sleep", lambda _: None)
    yield r


@pytest.fixture(autouse=True)
def _reset(client, admin_h):
    yield
    client.delete("/api/settings/llm", headers=admin_h)


OTHER = {"provider": "openai_compatible", "base_url": "https://llm.example.com/v1",
         "translate_model": "qwen-max", "analysis_model": "qwen-max"}


def test_default_and_permissions(client, admin_h, leader_h):
    assert client.get("/api/settings/llm", headers=leader_h).status_code == 403
    r = client.get("/api/settings/llm", headers=admin_h).json()
    assert r["source"] == "env" and r["provider"] == "deepseek" and r["translate_model"] == "deepseek-flash"
    assert r["presets"]["deepseek"]["analysis_model"] == "deepseek-v4-pro"


def test_switch_provider_requires_new_key(client, admin_h):
    r = client.put("/api/settings/llm", headers=admin_h, json=OTHER)
    assert r.status_code == 400 and "api_key" in r.text


def test_save_other_provider(client, admin_h, leader_h, rec):
    r = client.put("/api/settings/llm", headers=admin_h, json=OTHER | {"api_key": "sk-other-123456789"}).json()
    assert r["source"] == "db" and r["base_url"] == "https://llm.example.com/v1" and r["api_key_hint"] == "…6789"
    # Key 加密存库，留痕里没有 Key
    with SessionLocal() as db:
        raw = json.dumps(db.get(AppSetting, "llm").value)
        assert "sk-other" not in raw
        logs = db.scalars(select(AuditLog).where(AuditLog.entity_id == "llm")).all()
        assert logs and all("sk-other" not in (l.new_value or "") + (l.old_value or "") for l in logs)
    # 翻译请求发到新地址、新模型，而且不带 DeepSeek 的 thinking 参数
    t = client.post("/api/tasks", headers=leader_h, json={"client_id": "11111111-2222-3333-4444-555555555555",
                                                         "content": "换接口测试", "lang": "zh"})
    req = rec.reqs[-1]
    body = json.loads(req.content)
    assert str(req.url) == "https://llm.example.com/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-other-123456789"
    assert body["model"] == "qwen-max" and "thinking" not in body
    assert body["temperature"] == 0.3 and body["response_format"] == {"type": "json_object"}  # 基本设置不变
    got = client.get(f"/api/tasks/{t.json()['id']}", headers=leader_h).json()
    assert got["content"]["en"] == "Translation"
    # 同一地址改模型，不填 Key → 保留原 Key
    r = client.put("/api/settings/llm", headers=admin_h, json=OTHER | {"translate_model": "gpt-4o-mini"}).json()
    assert r["api_key_hint"] == "…6789" and llm_config.current().translate_model == "gpt-4o-mini"


def test_deepseek_preset_keeps_thinking_off(client, admin_h, rec):
    client.put("/api/settings/llm", headers=admin_h, json={"provider": "deepseek", "base_url": "",
               "translate_model": "deepseek-v4-pro", "api_key": "sk-ds-abcdefgh"})
    c = llm_config.current()
    assert c.base_url == "https://api.deepseek.com" and c.extra_body == {"thinking": {"type": "disabled"}}
    assert c.translate_model == "deepseek-v4-pro"


def test_test_connection_and_models(client, admin_h, rec):
    r = client.post("/api/settings/llm/test", headers=admin_h, json=OTHER | {"api_key": "sk-test-00000000"}).json()
    assert r["ok"] and r["en"] == "Translation" and r["model"] == "qwen-max"
    assert client.get("/api/settings/llm", headers=admin_h).json()["source"] == "env"  # 测试不保存
    rec.fail = True
    r = client.post("/api/settings/llm/test", headers=admin_h, json=OTHER | {"api_key": "sk-bad-00000000"}).json()
    assert not r["ok"] and "401" in r["error"]
    m = client.post("/api/settings/llm/models", headers=admin_h, json={"provider": "openai_compatible",
                    "base_url": "https://llm.example.com/v1", "api_key": "sk-x-00000000"}).json()
    assert m == ["gpt-4o-mini", "qwen-max"]


def test_bad_url_and_reset(client, admin_h):
    r = client.put("/api/settings/llm", headers=admin_h, json=OTHER | {"base_url": "ftp://x", "api_key": "k" * 10})
    assert r.status_code == 400
    client.put("/api/settings/llm", headers=admin_h, json=OTHER | {"api_key": "sk-other-123456789"})
    r = client.delete("/api/settings/llm", headers=admin_h).json()
    assert r["source"] == "env" and r["provider"] == "deepseek"


def test_env_key_never_sent_to_other_host(monkeypatch):
    """.env 里的 DeepSeek Key 只用于 DeepSeek 地址。"""
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "sk-env-deepseek")
    llm_config.invalidate()
    monkeypatch.setattr(llm_config, "_db_value", lambda: {"provider": "openai_compatible",
                        "base_url": "https://evil.example.com", "translate_model": "m", "api_key_enc": None})
    assert llm_config.current().api_key == ""
