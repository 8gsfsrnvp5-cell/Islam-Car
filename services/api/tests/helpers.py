"""Шаги сквозного сценария, которые переиспользуются в тестах."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.services.common import today

RUB = 100

COMPANY = {
    "seller_regime": "ip", "seller_name": "ИП Тестовый Продавец", "seller_inn": "000000000000",
    "seller_ogrn": "", "seller_address": "г. Тестовый, ул. Проверочная, 1", "support_phone": "+79000000000",
    "bank_payee": "ИП Тестовый Продавец", "bank_name": "Тестовый банк", "bank_bik": "000000000",
    "bank_account": "00000000000000000000", "bank_corr_account": "", "contract_prefix": "IC",
    "payment_purpose_hint": "Оплата по договору № {number}",
}


def setup_company(admin: TestClient) -> None:
    r = admin.put("/api/admin/settings", json=COMPANY)
    assert r.status_code == 200, r.text


def create_car(admin: TestClient, vin: str = "XTA21099012345678", owned: bool = True, publish: bool = True,
               purchase: int = 1_200_000, sale: int = 1_600_000) -> dict:
    r = admin.post("/api/admin/cars", json={
        "vin": vin, "make": "Toyota", "model": "Camry", "year": 2021, "mileage_km": 45000,
        "engine": "2.5 л, 181 л.с.", "transmission": "автомат", "color": "белый",
        "ownership_status": "owned" if owned else "purchasing", "status": "available",
        "purchase_price_kopecks": purchase * RUB, "purchase_date": (today() - timedelta(days=180)).isoformat(),
        "purchase_document": "ДКП № 15" if owned else "",
        "sale_price_kopecks": sale * RUB, "min_down_payment_kopecks": 300_000 * RUB, "max_term_months": 24,
    })
    assert r.status_code == 201, r.text
    car = r.json()
    if publish:
        r = admin.post(f"/api/admin/cars/{car['id']}/publish")
        assert r.status_code == 200, r.text
        car = r.json()
    return car


def create_verified_client(admin: TestClient, phone: str = "+7 900 111-22-33",
                           name: str = "Иванов Иван Иванович") -> dict:
    r = admin.post("/api/admin/clients", json={
        "party_type": "individual", "full_name": name, "phone": phone, "address": "г. Тестовый, ул. Клиентская, 2",
        "birth_date": "1990-05-01", "passport_number": "0000 000000", "passport_issued_by": "Тестовым отделом",
        "passport_issue_date": "2015-06-01",
    })
    assert r.status_code == 201, r.text
    client = r.json()
    r = admin.post(f"/api/admin/clients/{client['id']}/verify")
    assert r.status_code == 200, r.text
    return r.json()


def create_contract(admin: TestClient, client_id: str, car_id: str, contract_date: date | None = None,
                    sale: int = 1_600_000, down: int = 600_000, term: int = 20,
                    application_id: str | None = None) -> dict:
    contract_date = contract_date or today()
    first = contract_date + timedelta(days=30)
    r = admin.post("/api/admin/contracts", json={
        "client_id": client_id, "car_id": car_id, "sale_price_kopecks": sale * RUB,
        "down_payment_kopecks": down * RUB, "term_months": term, "contract_date": contract_date.isoformat(),
        "first_payment_date": first.isoformat(), "application_id": application_id,
    })
    assert r.status_code == 201, r.text
    return r.json()


def sign(admin: TestClient, contract: dict) -> dict:
    r = admin.post(f"/api/admin/contracts/{contract['id']}/sign",
                   json={"signed_on": contract["contract_date"], "confirm_paper_signed": True})
    assert r.status_code == 200, r.text
    return r.json()


def confirm_payment(admin: TestClient, contract_id: str, amount_rub: int, received_on: date | None = None,
                    doc: str = "п/п 1", **extra) -> dict:
    r = admin.post("/api/admin/payments", json={
        "contract_id": contract_id, "amount_kopecks": amount_rub * RUB,
        "received_on": (received_on or today()).isoformat(), "method": "bank_transfer",
        "document_ref": doc, **extra,
    })
    assert r.status_code == 201, r.text
    return r.json()


def buyer_session(admin: TestClient, client_id: str, password: str = "buyer-password-1") -> TestClient:
    r = admin.post(f"/api/admin/clients/{client_id}/access")
    assert r.status_code == 200, r.text
    access = r.json()
    token = access["activation_path"].split("token=")[1]
    buyer = TestClient(app)
    r = buyer.post("/api/auth/client/activate", json={"token": token, "password": password})
    assert r.status_code == 200, r.text
    r = buyer.post("/api/auth/client/login", json={"login": access["login"], "password": password})
    assert r.status_code == 200, r.text
    return buyer


def signed_deal(admin: TestClient, contract_date: date | None = None, vin: str = "XTA21099012345678",
                phone: str = "+7 900 111-22-33") -> tuple[dict, dict, dict]:
    """Автомобиль → клиент → подписанный договор. Возвращает (car, client, contract)."""
    setup_company(admin)
    car = create_car(admin, vin=vin)
    client = create_verified_client(admin, phone=phone)
    contract = sign(admin, create_contract(admin, client["id"], car["id"], contract_date=contract_date))
    return car, client, contract


def valid_png() -> bytes:
    import io

    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, "PNG")
    return buffer.getvalue()
