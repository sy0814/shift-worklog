from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    secret_key: str = "dev-only-secret-change-me-in-production-0000"
    app_timezone: str = "Europe/Belgrade"
    access_token_hours: int = 12

    admin_username: str = "admin"
    admin_password: str = "admin123"

    # ---- DeepSeek 翻译 / AI 分析 ----
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    # 附加到请求体里的参数（JSON），用来关闭思考模式等
    deepseek_extra_body: str = '{"thinking": {"type": "disabled"}}'
    translate_temperature: float = 0.3
    translate_timeout: float = 15.0
    translate_retries: int = 2  # 超时 / 网络错误后再试几次
    translate_max_attempts: int = 20  # 后台重试上限，超过后标记 failed，等管理员手动重试
    translate_retry_seconds: int = 120  # 后台重试间隔
    run_scheduler: bool = True  # 测试时关闭
    seed_demo: bool = False  # 第一次启动时建示例班组和班长账号（测试、开发、试用）；正式安装不建

    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 30
    max_photos_per_task: int = 50

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
