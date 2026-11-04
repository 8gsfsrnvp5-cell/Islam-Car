"""Учёт поступлений: подтверждение, «Я оплатил», сторно с сохранением истории."""

from datetime import timedelta

from app.services.common import today
from tests.helpers import RUB, buyer_session, confirm_payment, signed_deal


def test_client_report_does_not_change_balance_until_confirmed(admin):
    _, client, contract = signed_deal(admin)
    buyer = buyer_session(admin, client["id"])
    r = buyer.post(f"/api/client/contracts/{contract['id']}/payment-reports",
                   json={"amount_kopecks": 600_000 * RUB, "paid_on": today().isoformat(), "comment": "Перевод"})
    assert r.status_code == 201
    report_id = r.json()["id"]

    # Нажатие «Я оплатил» не считается поступлением
    view = buyer.get(f"/api/client/contracts/{contract['id']}").json()
    assert view["ledger"]["outstanding_kopecks"] == 1_600_000 * RUB
    assert view["reports"][0]["status"] == "pending"
    pending = admin.get("/api/admin/payment-reports").json()
    assert [p["id"] for p in pending] == [report_id]

    # Сотрудник нашёл деньги в банке и подтвердил платёж со ссылкой на сообщение
    confirm_payment(admin, contract["id"], 600_000, report_id=report_id)
    view = buyer.get(f"/api/client/contracts/{contract['id']}").json()
    assert view["ledger"]["outstanding_kopecks"] == 1_000_000 * RUB
    assert view["reports"][0]["status"] == "matched"
    assert admin.get("/api/admin/payment-reports").json() == []


def test_rejected_report_is_explained_to_client(admin):
    _, client, contract = signed_deal(admin)
    buyer = buyer_session(admin, client["id"])
    report = buyer.post(f"/api/client/contracts/{contract['id']}/payment-reports",
                        json={"amount_kopecks": 50_000 * RUB, "paid_on": today().isoformat()}).json()
    r = admin.post(f"/api/admin/payment-reports/{report['id']}/reject", json={"note": "Платёж не поступил на счёт"})
    assert r.status_code == 200
    notes = buyer.get("/api/client/notifications").json()
    assert any(n["body"] == "Платёж не поступил на счёт" for n in notes)


def test_wrong_payment_reversed_with_history_kept(admin):
    _, _, contract = signed_deal(admin)
    wrong = confirm_payment(admin, contract["id"], 60_000, doc="п/п 7")
    assert wrong["ledger_outstanding_kopecks"] == 1_540_000 * RUB

    r = admin.post(f"/api/admin/payments/{wrong['id']}/reverse", json={"reason": "Ошибка в сумме: 600 000"})
    assert r.status_code == 200
    assert r.json()["ledger_outstanding_kopecks"] == 1_600_000 * RUB
    assert admin.post(f"/api/admin/payments/{wrong['id']}/reverse", json={"reason": "повтор"}).status_code == 409

    fixed = confirm_payment(admin, contract["id"], 600_000, doc="п/п 7", corrects_payment_id=wrong["id"])
    assert fixed["ledger_outstanding_kopecks"] == 1_000_000 * RUB

    payments = admin.get(f"/api/admin/payments?contract_id={contract['id']}").json()
    by_id = {p["id"]: p for p in payments}
    assert by_id[wrong["id"]]["status"] == "reversed"  # исходная запись не удалена
    assert by_id[wrong["id"]]["reversal_reason"] == "Ошибка в сумме: 600 000"
    assert by_id[fixed["id"]]["corrects_payment_id"] == wrong["id"]

    actions = [a["action"] for a in admin.get(f"/api/admin/audit?entity_id={wrong['id']}").json()]
    assert actions == ["payment.reversed", "payment.confirmed"]


def test_payment_guards(admin):
    _, _, contract = signed_deal(admin)
    cid = contract["id"]
    base = {"contract_id": cid, "method": "bank_transfer", "document_ref": "п/п 1",
            "received_on": today().isoformat()}
    assert admin.post("/api/admin/payments", json={**base, "amount_kopecks": 1_600_001 * RUB}).status_code == 422
    future = (today() + timedelta(days=1)).isoformat()
    r = admin.post("/api/admin/payments", json={**base, "amount_kopecks": 100, "received_on": future})
    assert r.status_code == 422
    assert admin.post("/api/admin/payments", json={**base, "amount_kopecks": 100}).status_code == 201
    # Тот же банковский документ дважды не учитывается
    assert admin.post("/api/admin/payments", json={**base, "amount_kopecks": 100}).status_code == 409


def test_full_repayment_completes_contract_and_reversal_reopens(admin):
    _, client, contract = signed_deal(admin)
    paid = confirm_payment(admin, contract["id"], 1_600_000)
    assert paid["contract_status"] == "completed" and paid["ledger_outstanding_kopecks"] == 0
    assert admin.get(f"/api/admin/contracts/{contract['id']}").json()["status"] == "completed"
    admin.post(f"/api/admin/payments/{paid['id']}/reverse", json={"reason": "Платёж отозван банком"})
    assert admin.get(f"/api/admin/contracts/{contract['id']}").json()["status"] == "signed"


def test_payment_needs_signed_contract(admin):
    from tests.helpers import create_car, create_contract, create_verified_client, setup_company
    setup_company(admin)
    car = create_car(admin)
    client = create_verified_client(admin)
    draft = create_contract(admin, client["id"], car["id"])
    r = admin.post("/api/admin/payments", json={"contract_id": draft["id"], "amount_kopecks": 100,
                                                "received_on": today().isoformat(), "method": "cash",
                                                "document_ref": "ПКО 1"})
    assert r.status_code == 409
