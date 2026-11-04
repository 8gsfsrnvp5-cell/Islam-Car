from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки берутся из переменных окружения или файла .env (не хранится в git)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="development", description="development | test | production")
    database_url: str = "postgresql+psycopg://islamcar:islamcar@localhost:5433/islamcar"
    storage_dir: Path = Path("storage")

    # Сессии
    admin_session_hours: int = 12
    client_session_hours: int = 72
    cookie_secure: bool = False

    # Разрешённые Origin для изменяющих запросов (через прокси Next.js)
    allowed_origins: str = "http://localhost:3000,http://localhost:3001"

    # Защита от перебора паролей
    login_max_failures: int = 5
    login_window_minutes: int = 15

    company_timezone: str = "Europe/Moscow"
    max_photo_bytes: int = 10 * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
