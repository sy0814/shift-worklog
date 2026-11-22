"""AI 接口配置：管理员可在「系统设置」里改接口地址、Key、模型；没改过的用 .env 里的默认值（DeepSeek）。

只开放这几项。提示词、temperature、超时、重试等「基本设置」不在这里，保持不变。
"""

import json
import threading
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from . import secretbox
from .config import get_settings
from .db import SessionLocal
from .models import AppSetting

KEY = "llm"

# 预设：DeepSeek 需要显式关闭思考模式；其他 OpenAI 兼容接口不加附加参数（别家不认识 thinking 参数会报错）
PRESETS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "translate_model": "deepseek-flash",
        "analysis_model": "deepseek-v4-pro",
        "extra_body": {"thinking": {"type": "disabled"}},
    },
    "openai_compatible": {
        "base_url": "",
        "translate_model": "",
        "analysis_model": "",
        "extra_body": {},
    },
}


@dataclass
class LLMConfig:
    provider: str
    base_url: str
    api_key: str
    translate_model: str
    analysis_model: str
    extra_body: dict = field(default_factory=dict)
    source: str = "env"  # env：用 .env 默认；db：管理员在后台改过

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.translate_model)


def env_default() -> LLMConfig:
    s = get_settings()
    raw = s.deepseek_extra_body.strip()
    return LLMConfig(
        provider="deepseek",
        base_url=s.deepseek_base_url,
        api_key=s.deepseek_api_key,
        translate_model=s.deepseek_model,
        analysis_model=PRESETS["deepseek"]["analysis_model"],
        extra_body=json.loads(raw) if raw else {},
        source="env",
    )


_cache: dict | None = None  # 数据库里的覆盖值（未解密的原始 JSON）；None 表示还没读
_lock = threading.Lock()


def _db_value() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            with SessionLocal() as db:
                row = db.get(AppSetting, KEY)
                _cache = dict(row.value) if row and row.value else {}
        return _cache


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def current() -> LLMConfig:
    """当前生效的配置：数据库覆盖值优先，否则用 .env。"""
    v = _db_value()
    if not v:
        return env_default()
    preset = PRESETS.get(v.get("provider"), PRESETS["openai_compatible"])
    base_url = v.get("base_url") or preset["base_url"]
    key = secretbox.decrypt(v["api_key_enc"]) if v.get("api_key_enc") else None
    if key is None and _host(base_url) == _host(get_settings().deepseek_base_url):
        key = get_settings().deepseek_api_key  # 同一个服务才用 .env 里的 Key，绝不把它发给别的地址
    return LLMConfig(
        provider=v.get("provider", "openai_compatible"),
        base_url=base_url,
        api_key=key or "",
        translate_model=v.get("translate_model") or preset["translate_model"],
        analysis_model=v.get("analysis_model") or preset["analysis_model"],
        extra_body=dict(preset["extra_body"]),
        source="db",
    )


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def key_hint(key: str) -> str:
    return f"…{key[-4:]}" if len(key) >= 8 else ("…" if key else "")


def validate_base_url(url: str) -> str:
    url = url.strip().rstrip("/")
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("base_url must be http(s)://host[/path]")
    return url


def save(db: Session, *, provider: str, base_url: str, translate_model: str, analysis_model: str,
         api_key: str | None) -> dict:
    """保存覆盖值。api_key=None 表示不改；空字符串表示清掉（改用 .env 里的 Key）。返回留痕用的摘要。"""
    if provider not in PRESETS:
        raise ValueError("unknown provider")
    row = db.get(AppSetting, KEY)
    old = dict(row.value) if row and row.value else {}
    new = {
        "provider": provider,
        "base_url": validate_base_url(base_url or PRESETS[provider]["base_url"]),
        "translate_model": translate_model.strip(),
        "analysis_model": analysis_model.strip(),
        "api_key_enc": old.get("api_key_enc"),
    }
    if not new["translate_model"]:
        raise ValueError("translate_model required")
    old_url = old.get("base_url") or get_settings().deepseek_base_url
    if api_key is None and _host(new["base_url"]) != _host(old_url):
        # 换了服务地址却没填新 Key：不能把旧 Key 带到新地址
        raise ValueError("api_key required when changing the API host")
    if api_key is not None:
        new["api_key_enc"] = secretbox.encrypt(api_key.strip()) if api_key.strip() else None
    if row is None:
        db.add(AppSetting(key=KEY, value=new))
    else:
        row.value = new
    summary = {k: v for k, v in new.items() if k != "api_key_enc"}
    summary["api_key"] = "changed" if api_key is not None else "unchanged"
    return {"old": {k: v for k, v in old.items() if k != "api_key_enc"}, "new": summary}


def reset(db: Session) -> None:
    row = db.get(AppSetting, KEY)
    if row is not None:
        db.delete(row)
