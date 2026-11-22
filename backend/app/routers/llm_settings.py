"""系统设置 → AI 接口（仅管理员）。"""

import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, llm_config, translation_service, translator
from ..db import get_db
from ..models import User
from ..security import require_admin

router = APIRouter(prefix="/api/settings/llm", tags=["settings"])

SAMPLE = "3# 球磨机减速机轴承温度偏高，已通知机修。"


class LLMOut(BaseModel):
    provider: str
    base_url: str
    translate_model: str
    analysis_model: str
    api_key_set: bool
    api_key_hint: str
    source: str  # env / db
    presets: dict


class LLMIn(BaseModel):
    provider: str = Field(pattern="^(deepseek|openai_compatible)$")
    base_url: str = Field(default="", max_length=300)
    translate_model: str = Field(min_length=1, max_length=100)
    analysis_model: str = Field(default="", max_length=100)
    api_key: str | None = Field(default=None, max_length=500)  # None = 不修改


class TestIn(LLMIn):
    pass


class TestOut(BaseModel):
    ok: bool
    latency_ms: int
    model: str
    source_lang: str | None = None
    zh: str | None = None
    sr: str | None = None
    en: str | None = None
    error: str | None = None


class ModelsIn(BaseModel):
    provider: str = Field(pattern="^(deepseek|openai_compatible)$")
    base_url: str = Field(default="", max_length=300)
    api_key: str | None = Field(default=None, max_length=500)


def _out() -> LLMOut:
    c = llm_config.current()
    presets = {k: {kk: vv for kk, vv in v.items() if kk != "extra_body"} for k, v in llm_config.PRESETS.items()}
    return LLMOut(provider=c.provider, base_url=c.base_url, translate_model=c.translate_model,
                  analysis_model=c.analysis_model, api_key_set=bool(c.api_key),
                  api_key_hint=llm_config.key_hint(c.api_key), source=c.source, presets=presets)


def _candidate(body: LLMIn | ModelsIn) -> llm_config.LLMConfig:
    """用表单里的值组一个临时配置（不保存）。没填 Key 时，只有地址没换才沿用当前 Key。"""
    cur = llm_config.current()
    preset = llm_config.PRESETS[body.provider]
    try:
        base_url = llm_config.validate_base_url(body.base_url or preset["base_url"])
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    key = body.api_key.strip() if body.api_key else ""
    if not key:
        if llm_config._host(base_url) != llm_config._host(cur.base_url):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "api_key required when changing the API host")
        key = cur.api_key
    return llm_config.LLMConfig(
        provider=body.provider, base_url=base_url, api_key=key,
        translate_model=getattr(body, "translate_model", "") or preset["translate_model"],
        analysis_model=getattr(body, "analysis_model", "") or preset["analysis_model"],
        extra_body=dict(preset["extra_body"]), source="test")


@router.get("", response_model=LLMOut)
def get_llm(_: User = Depends(require_admin)):
    return _out()


@router.put("", response_model=LLMOut)
def put_llm(body: LLMIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        diff = llm_config.save(db, provider=body.provider, base_url=body.base_url,
                               translate_model=body.translate_model, analysis_model=body.analysis_model,
                               api_key=body.api_key)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    audit.log(db, user_id=admin.id, action="update", entity="setting", entity_id="llm",
              old=diff["old"], new=diff["new"])  # 不记录 Key 本身
    db.commit()
    llm_config.invalidate()
    return _out()


@router.delete("", response_model=LLMOut)
def reset_llm(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """恢复默认（.env 里的 DeepSeek 配置）。"""
    llm_config.reset(db)
    audit.log(db, user_id=admin.id, action="reset", entity="setting", entity_id="llm")
    db.commit()
    llm_config.invalidate()
    return _out()


@router.post("/test", response_model=TestOut)
def test_llm(body: TestIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """用表单里的配置（不保存）翻译一句示例，验证地址、Key、模型和 JSON 输出都可用。"""
    cfg = _candidate(body)
    t0 = time.monotonic()
    try:
        with translation_service.client_factory() as c:
            r = translator.translate(SAMPLE, translation_service.load_glossary(db), client=c, cfg=cfg)
        return TestOut(ok=True, latency_ms=int((time.monotonic() - t0) * 1000), model=cfg.translate_model,
                       source_lang=r.source_lang, zh=r.zh, sr=r.sr, en=r.en)
    except translator.TranslationError as e:
        return TestOut(ok=False, latency_ms=int((time.monotonic() - t0) * 1000), model=cfg.translate_model,
                       error=str(e)[:500])


@router.post("/models", response_model=list[str])
def list_models(body: ModelsIn, _: User = Depends(require_admin)):
    """从接口的 /models 读取可用模型列表（OpenAI 兼容格式）。"""
    cfg = _candidate(body)
    if not cfg.api_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "api_key required")
    try:
        with translation_service.client_factory() as c:
            r = c.get(cfg.base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {cfg.api_key}"},
                      timeout=15)
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"cannot reach API: {e}")
    if r.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        return sorted(m["id"] for m in r.json().get("data", []) if isinstance(m, dict) and m.get("id"))
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "unexpected /models response")
