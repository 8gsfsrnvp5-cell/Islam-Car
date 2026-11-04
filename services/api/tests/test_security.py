"""Разграничение доступа: покупатель видит только своё, сотрудники — по ролям."""

import os

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, engine, make_engine
from app.main import app
from app.models import Role, User
from tests.conftest import OWNER_LOGIN, OWNER_PASSWORD, staff_client
from tests.helpers import (
    RUB,
    buyer_session,
    create_car,
    create_contract,
    create_verified_client,
    signed_deal,
)


def test_buyer_cannot_see_other_buyers_data(admin):
    _, client_a, contract_a = signed_deal(admin)
    car_b = create_car(admin, vin="XTA21099087654321")
    client_b = create_verified_client(admin, phone="+79005556677", name="Сидоров Сидор")
    contract_b = create_contract(admin, client_b["id"], car_b["id"])
    from tests.helpers import sign
    contract_b = sign(admin, contract_b)

    buyer_a = buyer_session(admin, client_a["id"])
    assert [c["id"] for c in buyer_a.get("/api/client/contracts").json()] == [contract_a["id"]]
    for path in (f"/api/client/contracts/{contract_b['id']}", f"/api/client/contracts/{contract_b['id']}/schedule.csv"):
        assert buyer_a.get(path).status_code == 404
    r = buyer_a.post(f"/api/client/contracts/{contract_b['id']}/payment-reports",
                     json={"amount_kopecks": 100, "paid_on": "2026-11-01"})
    assert r.status_code == 404

    # Сессия покупателя не открывает административные маршруты
    assert buyer_a.get("/api/admin/contracts").status_code == 401
    assert buyer_a.get("/api/admin/dashboard").status_code == 401


def test_buyer_does_not_see_draft_contracts(admin):
    _, client, _ = signed_deal(admin)
    car2 = create_car(admin, vin="XTA21099011111111")
    draft = create_contract(admin, client["id"], car2["id"])
    buyer = buyer_session(admin, client["id"])
    assert len(buyer.get("/api/client/contracts").json()) == 1
    assert buyer.get(f"/api/client/contracts/{draft['id']}").status_code == 404


def test_anonymous_has_no_access(public):
    assert public.get("/api/admin/clients").status_code == 401
    assert public.get("/api/client/contracts").status_code == 401


def test_role_restrictions(admin):
    _, _, contract = signed_deal(admin)
    manager = staff_client("manager@islamic-car.test", Role.manager)
    accountant = staff_client("accountant@islamic-car.test", Role.accountant)

    car = manager.get(f"/api/admin/cars/{contract['car']['id']}").json()
    assert "purchase_price_kopecks" not in car  # закупочная цена скрыта от менеджера
    assert "markup_kopecks" not in manager.get(f"/api/admin/contracts/{contract['id']}").json()
    assert "finance" not in manager.get("/api/admin/dashboard").json()
    r = manager.post("/api/admin/payments", json={"contract_id": contract["id"], "amount_kopecks": 100,
                                                  "received_on": contract["contract_date"], "method": "cash",
                                                  "document_ref": "ПКО 1"})
    assert r.status_code == 403
    assert manager.get("/api/admin/users").status_code == 403

    assert accountant.post("/api/admin/cars", json={"make": "Lada", "model": "Vesta", "year": 2024,
                                                    "sale_price_kopecks": 100 * RUB}).status_code == 403
    clients = accountant.get("/api/admin/clients").json()
    assert clients[0]["pd_masked"] and "•" in clients[0]["passport_number"]


def test_login_throttling(owner):
    c = TestClient(app)
    for _ in range(5):
        assert c.post("/api/auth/admin/login", json={"login": OWNER_LOGIN, "password": "wrong"}).status_code == 401
    r = c.post("/api/auth/admin/login", json={"login": OWNER_LOGIN, "password": OWNER_PASSWORD})
    assert r.status_code == 429


def test_owner_second_factor(admin):
    secret = admin.post("/api/auth/admin/totp/setup").json()["secret"]
    assert admin.post("/api/auth/admin/totp/enable", json={"code": pyotp.TOTP(secret).now()}).status_code == 200

    c = TestClient(app)
    r = c.post("/api/auth/admin/login", json={"login": OWNER_LOGIN, "password": OWNER_PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "totp_required"
    r = c.post("/api/auth/admin/login", json={"login": OWNER_LOGIN, "password": OWNER_PASSWORD,
                                              "totp_code": pyotp.TOTP(secret).at(__import__("time").time() + 30)})
    assert r.status_code == 200


def test_logout_revokes_session(admin):
    assert admin.post("/api/auth/admin/logout").status_code == 200
    assert admin.get("/api/admin/dashboard").status_code == 401


def test_foreign_origin_rejected(admin):
    r = admin.post("/api/admin/cars", headers={"Origin": "https://evil.example"},
                   json={"make": "Lada", "model": "Vesta", "year": 2024, "sale_price_kopecks": 100})
    assert r.status_code == 403


def test_activation_link_is_single_use(admin):
    _, client, _ = signed_deal(admin)
    path = admin.post(f"/api/admin/clients/{client['id']}/access").json()["activation_path"]
    token = path.split("token=")[1]
    c = TestClient(app)
    assert c.post("/api/auth/client/activate", json={"token": token, "password": "short"}).status_code == 422
    assert c.post("/api/auth/client/activate", json={"token": token, "password": "long-password-1"}).status_code == 200
    assert c.post("/api/auth/client/activate", json={"token": token, "password": "long-password-2"}).status_code == 400


def test_identity_change_resets_verification(admin):
    client = create_verified_client(admin)
    r = admin.patch(f"/api/admin/clients/{client['id']}", json={"passport_number": "1111 111111"})
    assert r.json()["identity_verified"] is False


def test_password_hashes_are_not_plaintext(owner):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == OWNER_LOGIN))
        assert user.password_hash.startswith("$argon2") and OWNER_PASSWORD not in user.password_hash


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="Проверка сохранности данных — только на PostgreSQL")
def test_data_survives_reconnect(admin):
    """Аналог перезапуска сервера: новое подключение к базе видит все данные."""
    _, _, contract = signed_deal(admin)
    fresh = make_engine(os.environ["DATABASE_URL"])
    with fresh.connect() as conn:
        from sqlalchemy import text
        number = conn.execute(text("select number from contracts where status = 'signed'")).scalar()
    fresh.dispose()
    assert number == contract["number"]
