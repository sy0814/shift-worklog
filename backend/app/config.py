from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    secret_key: str = "dev-only-secret-change-me-in-production-0000"
    app_timezone: str = "Europe/Belgrade"
    access_token_hours: int = 12

    admin_username: str = "admin"
    admin_password: str = "admin123"

    deepseek_api_key: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
