"""Версия 4: расширенная аналитика, управленческий прогноз, выгрузки XLSX."""

import io
from datetime import timedelta

from openpyxl import load_workbook

from app.models import Role
from app.services.common import today
from app.services.finance_model import month_key
from tests.conftest import staff_client
from tests.helpers import (
    RUB,
    confirm_payment,
    create_car,
    create_contract,
    create_verified_client,
    setup_company,
    sign,
    signed_deal,
)


def test_analytics_plan_fact_aging_and_forecast(admin):
    start = today() - timedelta(days=70)
    _, _, contract = signed_deal(admin, contract_date=start)  # просрочено 600 000 (70 дн.), 50 000 (40), 50 000 (10)
    confirm_payment(admin, contract["id"], 600_000)

    r = admin.get("/api/admin/analytics?months=6")
    assert r.status_code == 200, r.text
    a = r.json()
    by_month = {m["month"]: m for m in a["monthly"]}
    assert by_month[month_key(start)]["planned_kopecks"] >= 600_000 * RUB
    current = by_month[month_key(today())]
    assert current["collected_kopecks"] == 600_000 * RUB and current["by_source"]["staff"] == 600_000 * RUB

    aging = {b["code"]: b for b in a["aging"]}
    assert aging["0_30"]["amount_kopecks"] == 50_000 * RUB and aging["31_90"]["amount_kopecks"] == 50_000 * RUB
    assert aging["31_90"]["contracts"] == 1 and a["kpi"]["contracts_overdue"] == 1
    assert a["kpi"]["overdue_kopecks"] == 100_000 * RUB

    fc = a["forecast"]
    assert fc["label"] == "ПРОГНОЗ" and fc["warnings"]  # методика резерва не утверждена — об этом сказано
    first = next(row for row in fc["rows"] if row["scheduled_kopecks"])
    assert first["scheduled_kopecks"] == 50_000 * RUB
    assert first["risk_adjusted_kopecks"] == 35_000 * RUB  # просрочка 31–90 дн. → 30% по методике по умолчанию
    assert fc["overdue_recovery_kopecks"] == 80_000 * RUB  # 50 000 × 90% + 50 000 × 70%


def test_funnel_counts_applications(admin, public):
    setup_company(admin)
    car = create_car(admin)
    for i in range(3):
        r = public.post("/api/public/applications", json={
            "kind": "catalog", "car_id": car["id"], "name": f"Покупатель {i}", "phone": f"+7 900 000-00-0{i}",
            "consent_personal_data": True})
        assert r.status_code == 201, r.text
    a = admin.get("/api/admin/analytics").json()
    funnel = {f["code"]: f for f in a["funnel"]}
    assert funnel["all"]["count"] == 3 and funnel["converted"]["count"] == 0
    assert a["kpi"]["conversion"] == 0.0


def test_xlsx_exports_are_typed_and_safe(admin):
    setup_company(admin)
    car = create_car(admin)
    client = create_verified_client(admin, name='=HYPERLINK("http://evil.test","Иванов")')
    contract = sign(admin, create_contract(admin, client["id"], car["id"]))
    confirm_payment(admin, contract["id"], 600_000)

    r = admin.get("/api/admin/analytics.xlsx")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Сводка", "План и факт", "Продажи", "Просрочка", "Заявки", "Прогноз"]
    texts = [c.value for row in wb["Прогноз"].iter_rows() for c in row if isinstance(c.value, str)]
    assert any(t.startswith("ПРОГНОЗ") for t in texts)

    wb = load_workbook(io.BytesIO(admin.get("/api/admin/reports/contracts.xlsx").content))
    row = [c for c in wb.active[2]]
    assert row[2].data_type == "s" and row[2].value.startswith("=HYPERLINK")  # текст, а не формула
    assert row[6].value == 1_600_000 and row[6].number_format == "#,##0.00"

    wb = load_workbook(io.BytesIO(admin.get("/api/admin/reports/payments.xlsx").content))
    assert wb.active["D2"].value == 600_000 and wb.active["G2"].value == "Сотрудник"

    csv_text = admin.get("/api/admin/reports/contracts.csv").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in csv_text and ';"=HYPERLINK' not in csv_text  # в CSV формула экранирована

    assert admin.get("/api/admin/reports/bank.xlsx").status_code == 200


def test_analytics_requires_reports_permission(admin):
    manager = staff_client("manager1", Role.manager)
    assert manager.get("/api/admin/analytics").status_code == 403
    assert manager.get("/api/admin/analytics.xlsx").status_code == 403
