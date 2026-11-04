from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки берутся из переменных окружения или файла .env (не хранится в git)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
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
    max_document_bytes: int = 20 * 1024 * 1024

    # Второй фактор для владельца: по умолчанию обязателен в production
    require_owner_2fa: bool | None = None

    # Документы: каталог утверждённых шаблонов и шрифт с кириллицей для PDF
    templates_dir: Path = Path(__file__).resolve().parents[3] / "templates" / "contracts"
    document_font_dir: Path | None = None
    # Библиотеки знаний (legal, accounting, islamic-finance) и срок, после которого проверка считается устаревшей
    knowledge_dir: Path = Path(__file__).resolve().parents[3] / "knowledge"
    knowledge_stale_days: int = 180

    # Каналы уведомлений. "log" — тестовый режим: сообщение пишется в журнал, наружу не уходит (запрещён в production)
    sms_provider: str = ""
    email_provider: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    # SMS.ru: нужен договор с оператором и согласованное имя отправителя. test=1 — сообщение не отправляется
    smsru_api_id: str = ""
    smsru_from: str = ""
    smsru_test: bool = False

    # Онлайн-оплата. "sandbox" — тестовая оплата без денег (запрещена в production), "yookassa" — ЮKassa
    payment_provider: str = ""
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_api_url: str = "https://api.yookassa.ru/v3"
    # Чеки по 54-ФЗ настраивает бухгалтер. Пока владелец не подтвердил, онлайн-оплата в production выключена
    payment_receipts_confirmed: bool = False
    # Адрес кабинета покупателя, куда платёжный сервис возвращает после оплаты
    client_public_url: str = "http://localhost:3000"

    # Помощник по библиотекам знаний (Claude API). Без ключа выключен; включает владелец в настройках
    anthropic_api_key: str = ""
    assistant_model: str = "claude-opus-5-5"
    assistant_timeout_seconds: float = 60.0

    # Фоновый обработчик
    worker_poll_seconds: float = 5.0
    reminders_every_minutes: int = 30

    # Резервные копии (выполняет фоновый обработчик, только для PostgreSQL)
    backup_dir: Path | None = None
    backup_retention_days: int = 30
    backup_hour: int = 3
    pg_dump_path: str = "pg_dump"
    pg_restore_path: str = "pg_restore"
    backup_verify_database_url: str = ""

    @field_validator("require_owner_2fa", "backup_dir", "document_font_dir", mode="before")
    @classmethod
    def empty_is_unset(cls, value):
        # docker compose передаёт незаданные переменные как пустую строку
        return None if value == "" else value

    @model_validator(mode="after")
    def production_safety(self):
        if self.is_production:
            if not self.cookie_secure or self.require_owner_2fa is False:
                raise ValueError("Production requires COOKIE_SECURE=true and owner 2FA")
            urls = [*self.origins, self.client_public_url]
            if not self.origins or any(urlsplit(u).scheme != "https" or not urlsplit(u).hostname
                                       or "*" in u or urlsplit(u).username for u in urls):
                raise ValueError("Production requires explicit HTTPS origins and client URL")
            if (self.sms_provider == "log" or self.email_provider == "log" or self.smsru_test
                    or self.payment_provider == "sandbox" or self.yookassa_secret_key.startswith("test_")):
                raise ValueError("Test providers are forbidden in production")
            if self.yookassa_api_url != "https://api.yookassa.ru/v3":
                raise ValueError("Production payments require the official YooKassa endpoint")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def owner_2fa_required(self) -> bool:
        return self.is_production if self.require_owner_2fa is None else self.require_owner_2fa

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
