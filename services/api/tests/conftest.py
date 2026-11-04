"""Тестовая база изолирована от рабочей.

По умолчанию — SQLite в памяти. Для проверки на PostgreSQL задайте TEST_DATABASE_URL
(отдельная база, например islamcar_test). Рабочую DATABASE_URL тесты не используют.
"""

import os
import tempfile

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://")
os.environ["ENVIRONMENT"] = "test"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="islamcar-test-")
# Внешние каналы в тестовом режиме: сообщения пишутся в журнал, наружу ничего не уходит
os.environ["SMS_PROVIDER"] = "log"
os.environ["EMAIL_PROVIDER"] = "log"
os.environ["PAYMENT_PROVIDER"] = ""
os.environ["SMSRU_API_ID"] = ""
# Переменные окружения важнее файла .env: локальные настройки стенда не влияют на тесты
os.environ["BACKUP_DIR"] = ""
os.environ["REQUIRE_OWNER_2FA"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402

OWNER_LOGIN = "owner@islamic-car.test"
OWNER_PASSWORD = "owner-password-1"


@pytest.fixture(scope="session", autouse=True)
def schema():
    if engine.dialect.name == "postgresql":
        db_name = engine.url.database or ""
        assert "test" in db_name, "Тесты запускаются только на базе с 'test' в имени"
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            names = ", ".join(t.name for t in Base.metadata.sorted_tables)
            conn.execute(text(f"TRUNCATE {names} CASCADE"))
        else:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


def make_user(login: str, password: str, role: Role, full_name: str = "Сотрудник") -> User:
    with SessionLocal() as db:
        user = User(login=login, full_name=full_name, role=role, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        return user


@pytest.fixture
def owner():
    return make_user(OWNER_LOGIN, OWNER_PASSWORD, Role.owner, "Владелец")


@pytest.fixture
def admin(owner) -> TestClient:
    """Клиент API с сессией владельца."""
    c = TestClient(app)
    r = c.post("/api/auth/admin/login", json={"login": OWNER_LOGIN, "password": OWNER_PASSWORD})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def public() -> TestClient:
    return TestClient(app)


def staff_client(login: str, role: Role) -> TestClient:
    password = "staff-password-1"
    make_user(login, password, role)
    c = TestClient(app)
    assert c.post("/api/auth/admin/login", json={"login": login, "password": password}).status_code == 200
    return c
