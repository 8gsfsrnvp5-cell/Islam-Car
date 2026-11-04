"""Версия 3: налоговые расчёты только по утверждённым правилам, журнал операций, календарь."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Role, StaffTask
from app.services import staff_tasks
from app.services.common import today
from tests.conftest import staff_client
from tests.helpers import COMPANY, RUB, confirm_payment, signed_deal

SOURCE = "http://publication.pravo.gov.ru/document/test-source"


def year() -> tuple[str, str]:
    t = today()
    return t.replace(month=1, day=1).isoformat(), t.isoformat()


def add_param(client, code: str, value: str, start: str | None = None, end: str | None = None):
    r = client.post("/api/admin/accounting/params", json={
        "code": code, "value": value, "effective_from": start or today().replace(month=1, day=1).isoformat(),
        "effective_to": end, "source_url": SOURCE, "note": "тестовое значение"})
    assert r.status_code == 201, r.text
    return r.json()


def calc(admin) -> dict:
    start, end = year()
    return admin.get(f"/api/admin/accounting/calculate?date_from={start}&date_to={end}").json()


def test_no_tax_without_approved_rules(admin):
    _, _, contract = signed_deal(admin)
    confirm_payment(admin, contract["id"], 600_000)
    assert calc(admin)["warnings"][0].startswith("Налоговый режим не выбран")
    admin.put("/api/admin/accounting/profile", json={"tax_regime": "usn_income", "vat_payer": False})
    result = calc(admin)["results"][0]
    assert result["status"] == "not_configured" and result["amount_kopecks"] is None
    assert "Нет утверждённых параметров" in result["warnings"][0]

    draft = add_param(admin, "usn_income_rate", "6")
    assert calc(admin)["results"][0]["status"] == "not_configured"  # черновик не используется
    assert admin.post(f"/api/admin/accounting/params/{draft['id']}/approve").status_code == 200
    result = calc(admin)["results"][0]
    assert result["status"] == "ok" and result["amount_kopecks"] == 36_000 * RUB  # 600 000 × 6% (тестовое значение)
    assert result["params"][0]["source_url"] == SOURCE and result["params"][0]["approved_by"] == "Владелец"
    assert "acc.nk.346_20" in result["basis"] and result["steps"][0]["value_kopecks"] == 600_000 * RUB


def test_rate_change_inside_period_blocks_calculation(admin):
    admin.put("/api/admin/settings", json=COMPANY)
    admin.put("/api/admin/accounting/profile", json={"tax_regime": "usn_income", "vat_payer": False})
    first = add_param(admin, "usn_income_rate", "6")
    admin.post(f"/api/admin/accounting/params/{first['id']}/approve")
    second = add_param(admin, "usn_income_rate", "5", start=today().isoformat())
    assert admin.post(f"/api/admin/accounting/params/{second['id']}/approve").status_code == 409  # пересечение
    admin.post(f"/api/admin/accounting/params/{first['id']}/revoke")
    closed = add_param(admin, "usn_income_rate", "6", end=(today() - timedelta(days=1)).isoformat())
    admin.post(f"/api/admin/accounting/params/{closed['id']}/approve")
    assert admin.post(f"/api/admin/accounting/params/{second['id']}/approve").status_code == 200
    if today().month == 1 and today().day == 1:
        return  # период из одного дня — смены ставки внутри нет
    data = calc(admin)
    assert data["results"][0]["status"] == "not_configured"
    assert any("менялось внутри периода" in w for w in data["warnings"])


def test_usn_income_minus_expenses_with_minimum_tax(admin):
    _, _, contract = signed_deal(admin)
    confirm_payment(admin, contract["id"], 600_000)
    admin.put("/api/admin/accounting/profile", json={"tax_regime": "usn_income_expense", "vat_payer": False})
    for code, value in (("usn_ie_rate", "15"), ("usn_min_tax_rate", "1")):
        admin.post(f"/api/admin/accounting/params/{add_param(admin, code, value)['id']}/approve")
    r = calc(admin)["results"][0]
    # Доходы 600 000; расходы — стоимость проданного автомобиля 1 200 000 → убыток, платится минимальный налог 1%
    assert r["status"] == "ok" and r["amount_kopecks"] == 6_000 * RUB
    assert any("убыток" in w for w in r["warnings"])


def test_ndfl_for_one_off_seller_and_holding_exemption(admin):
    _, _, contract = signed_deal(admin)
    admin.put("/api/admin/settings", json={**COMPANY, "seller_regime": "individual_one_off"})
    confirm_payment(admin, contract["id"], 800_000)
    assert admin.put("/api/admin/accounting/profile",
                     json={"tax_regime": "usn_income", "vat_payer": False}).status_code == 422
    admin.put("/api/admin/accounting/profile", json={"tax_regime": "individual_ndfl", "vat_payer": False})
    for code, value in (("ndfl_rate", "13"), ("ndfl_property_deduction", "250000"), ("ndfl_min_holding_years", "3")):
        admin.post(f"/api/admin/accounting/params/{add_param(admin, code, value)['id']}/approve")
    r = calc(admin)["results"][0]
    # Цена 1 600 000 − расходы 1 200 000 = 400 000; поступило 800 000 = половина → облагается 200 000 × 13%
    assert r["status"] == "ok" and r["amount_kopecks"] == 26_000 * RUB


def test_vat_on_margin_for_cars_bought_from_individuals(admin):
    car, _, contract = signed_deal(admin)
    with SessionLocal() as db:
        from app.models import Car
        db.get(Car, __import__("uuid").UUID(car["id"])).purchased_from = "individual"
        db.commit()
    admin.put("/api/admin/accounting/profile", json={"tax_regime": "usn_income", "vat_payer": True})
    admin.post(f"/api/admin/accounting/params/{add_param(admin, 'vat_rate', '20')['id']}/approve")
    vat = next(r for r in calc(admin)["results"] if r["code"] == "vat_margin")
    # Межценовая разница 400 000 × 20/120
    assert vat["status"] == "ok" and vat["amount_kopecks"] == 6_666_667


def test_operations_journal(admin):
    _, _, contract = signed_deal(admin)
    confirm_payment(admin, contract["id"], 600_000)
    admin.post("/api/admin/expenses", json={"spent_on": today().isoformat(), "category": "Аренда",
                                            "amount_kopecks": 50_000 * RUB})
    start, end = year()
    ops = admin.get(f"/api/admin/accounting/operations?date_from={start}&date_to={end}").json()
    assert ops["totals"]["receipts"] == 600_000 * RUB and ops["totals"]["expenses"] == 50_000 * RUB
    assert ops["sales"][0]["markup"] == 400_000 * RUB


def test_tax_calendar_creates_deadline_task(admin):
    r = admin.post("/api/admin/accounting/calendar", json={
        "title": "Авансовый платёж по УСН (дата внесена бухгалтером)",
        "due_date": (today() + timedelta(days=5)).isoformat(),
        "knowledge_code": "acc.nk.346_21"})
    assert r.status_code == 201
    with SessionLocal() as db:
        staff_tasks.scan(db, datetime.now(UTC))
        db.commit()
        assert db.scalar(select(StaffTask).where(StaffTask.kind == "tax_deadline"))


def test_accounting_roles(admin):
    accountant = staff_client("accountant@islamic-car.test", Role.accountant)
    manager = staff_client("manager@islamic-car.test", Role.manager)
    assert manager.get("/api/admin/accounting/params").status_code == 403
    param = add_param(accountant, "usn_income_rate", "6")
    assert accountant.post(f"/api/admin/accounting/params/{param['id']}/approve").status_code == 403
    assert admin.post(f"/api/admin/accounting/params/{param['id']}/approve").status_code == 200
