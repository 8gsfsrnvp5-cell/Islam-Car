"""Версия 4: онлайн-оплата (тестовый провайдер и ЮKassa) и SMS.ru."""

import pytest

from app.config import get_settings
from app.models import Channel
from app.services import online_payments, providers
from app.services.common import today
from app.services.providers import ProviderError, SmsRuProvider, get_provider
from tests.helpers import RUB, buyer_session, confirm_payment, signed_deal


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setattr(get_settings(), "payment_provider", "sandbox")


def contract_payments(admin, contract_id: str) -> list[dict]:
    payments = admin.get(f"/api/admin/contracts/{contract_id}").json()["payments"]
    return [p for p in payments if p["status"] == "confirmed"]


def start(buyer, contract_id: str, rub: int):
    return buyer.post(f"/api/client/contracts/{contract_id}/online-payments", json={"amount_kopecks": rub * RUB})


def test_online_payment_disabled_by_default(admin):
    _, client, contract = signed_deal(admin)
    buyer = buyer_session(admin, client["id"])
    assert buyer.get("/api/client/online-payment").json() == {"enabled": False, "provider": "", "test_mode": False}
    assert start(buyer, contract["id"], 1000).status_code == 409


def test_sandbox_payment_counts_only_after_provider_status(admin, sandbox):
    _, client, contract = signed_deal(admin)
    buyer = buyer_session(admin, client["id"])
    assert buyer.get("/api/client/online-payment").json()["test_mode"] is True
    r = start(buyer, contract["id"], 600_000)
    assert r.status_code == 201, r.text
    intent = r.json()
    assert intent["status"] == "pending" and intent["confirmation_url"] == f"/cabinet/payments/{intent['id']}"

    # Возврат на сайт и «уведомление» с выдуманным статусом ничего не учитывают
    assert buyer.get(f"/api/client/online-payments/{intent['id']}").json()["status"] == "pending"
    sbx_id = admin.get("/api/admin/payment-intents").json()[0]["provider_payment_id"]
    fake = {"event": "payment.succeeded", "object": {"id": sbx_id, "status": "succeeded"}}
    assert admin.post("/api/payments/webhook/sandbox", json=fake).status_code == 200
    assert not contract_payments(admin, contract["id"])

    r = buyer.post(f"/api/client/online-payments/{intent['id']}/sandbox", json={"result": "succeeded"})
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    payments = contract_payments(admin, contract["id"])
    assert len(payments) == 1
    assert (payments[0]["source"], payments[0]["method"], payments[0]["amount_kopecks"]) == \
        ("provider", "online", 600_000 * RUB)

    # Повторные проверки и уведомления безопасны
    buyer.get(f"/api/client/online-payments/{intent['id']}")
    admin.post("/api/payments/webhook/sandbox", json=fake)
    assert len(contract_payments(admin, contract["id"])) == 1
    assert buyer.post(f"/api/client/online-payments/{intent['id']}/sandbox",
                      json={"result": "succeeded"}).status_code == 409


def test_sandbox_cancel_and_isolation(admin, sandbox):
    _, client, contract = signed_deal(admin)
    buyer = buyer_session(admin, client["id"])
    intent = start(buyer, contract["id"], 1000).json()
    r = buyer.post(f"/api/client/online-payments/{intent['id']}/sandbox", json={"result": "canceled"})
    assert r.json()["status"] == "canceled" and not contract_payments(admin, contract["id"])
    assert start(buyer, contract["id"], 5_000_000).status_code == 422  # больше остатка

    _, other, _ = signed_deal(admin, vin="XTA21099012345679", phone="+7 900 222-33-44")
    stranger = buyer_session(admin, other["id"], password="other-password-1")
    assert stranger.get(f"/api/client/online-payments/{intent['id']}").status_code == 404


def test_sandbox_is_never_used_in_production(monkeypatch, sandbox):
    monkeypatch.setattr(get_settings(), "environment", "production")
    assert online_payments.get_payment_provider() is None


def test_paid_but_not_applicable_goes_to_staff_review(admin, sandbox):
    _, client, contract = signed_deal(admin)
    buyer = buyer_session(admin, client["id"])
    intent = start(buyer, contract["id"], 1_600_000).json()  # весь остаток
    confirm_payment(admin, contract["id"], 600_000)          # тем временем пришёл банковский перевод
    r = buyer.post(f"/api/client/online-payments/{intent['id']}/sandbox", json={"result": "succeeded"})
    assert r.json()["status"] == "needs_review"
    staff_view = admin.get("/api/admin/payment-intents?status=needs_review").json()[0]
    assert "больше остатка" in staff_view["error"]
    tasks = admin.get("/api/admin/tasks").json()
    assert any("требует проверки" in t["title"] for t in (tasks if isinstance(tasks, list) else tasks["items"]))
    assert len(contract_payments(admin, contract["id"])) == 1  # только банковский перевод


class FakeYooKassa:
    def __init__(self):
        self.calls: list[tuple] = []
        self.remote_status = "pending"

    def __call__(self, method, url, *, json_body=None, form=None, headers=None, basic_auth=None):
        self.calls.append((method, url, json_body, headers, basic_auth))
        amount = {"value": "50000.00", "currency": "RUB"}
        if method == "POST":
            return {"id": "yk-1", "status": "pending", "amount": amount,
                    "confirmation": {"type": "redirect", "confirmation_url": "https://yoomoney.ru/checkout/yk-1"}}
        return {"id": "yk-1", "status": self.remote_status, "amount": amount, "paid": self.remote_status == "succeeded",
                "captured_at": f"{today().isoformat()}T08:30:00.000Z"}


def test_yookassa_adapter_rechecks_status(admin, monkeypatch):
    s = get_settings()
    for k, v in {"payment_provider": "yookassa", "yookassa_shop_id": "000000", "yookassa_secret_key": "test_x"}.items():
        monkeypatch.setattr(s, k, v)
    fake = FakeYooKassa()
    monkeypatch.setattr(online_payments, "request_json", fake)
    _, client, contract = signed_deal(admin)
    buyer = buyer_session(admin, client["id"])
    intent = start(buyer, contract["id"], 50_000).json()
    assert intent["confirmation_url"] == "https://yoomoney.ru/checkout/yk-1"
    method, url, body, headers, auth = fake.calls[0]
    assert method == "POST" and url.endswith("/payments") and auth == ("000000", "test_x")
    assert body["amount"] == {"value": "50000.00", "currency": "RUB"} and body["capture"] is True
    assert "receipt" not in body and headers["Idempotence-Key"]
    assert body["confirmation"]["return_url"].endswith(f"/cabinet/payments/{intent['id']}")

    webhook = {"type": "notification", "event": "payment.succeeded", "object": {"id": "yk-1", "status": "succeeded"}}
    admin.post("/api/payments/webhook/yookassa", json=webhook)
    assert fake.calls[-1][0] == "GET" and not contract_payments(admin, contract["id"])

    fake.remote_status = "succeeded"
    admin.post("/api/payments/webhook/yookassa", json=webhook)
    payments = contract_payments(admin, contract["id"])
    assert len(payments) == 1 and payments[0]["external_ref"] == "yookassa:yk-1"
    assert payments[0]["received_on"] == today().isoformat()


def test_yookassa_needs_receipt_decision_in_production(monkeypatch):
    s = get_settings()
    for k, v in {"payment_provider": "yookassa", "yookassa_shop_id": "1", "yookassa_secret_key": "live_x",
                 "environment": "production"}.items():
        monkeypatch.setattr(s, k, v)
    assert online_payments.get_payment_provider() is None
    monkeypatch.setattr(s, "payment_receipts_confirmed", True)
    assert online_payments.get_payment_provider().name == "yookassa"


def test_smsru_adapter(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "sms_provider", "smsru")
    monkeypatch.setattr(s, "smsru_api_id", "test-api-id")
    sent = {}

    def fake(method, url, *, form=None, **kw):
        sent.update(form)
        return {"status": "OK", "status_code": 100, "sms": {"79001112233": {"status": "OK", "sms_id": "000-1"}}}

    monkeypatch.setattr(providers, "request_json", fake)
    p = get_provider(Channel.sms)
    assert isinstance(p, SmsRuProvider) and not p.test_mode
    assert p.send("8 (900) 111-22-33", "", "Напоминание о платеже") == "000-1"
    assert sent["to"] == "79001112233" and sent["msg"] == "Напоминание о платеже" and "test" not in sent

    monkeypatch.setattr(providers, "request_json", lambda *a, **k: {"status": "ERROR", "status_text": "Нет денег"})
    with pytest.raises(ProviderError, match="Нет денег"):
        p.send("+79001112233", "", "x")
    with pytest.raises(ProviderError):
        p.send("+1 202 555 0100", "", "x")

    monkeypatch.setattr(s, "smsru_test", True)
    monkeypatch.setattr(s, "environment", "production")
    assert get_provider(Channel.sms) is None  # тестовый режим в production считал бы сообщения отправленными
