"""Версия 3: финансовый резерв, сценарии, рентабельность, проверка автомобиля, агенты."""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select

from app.agents.base import Agent, Finding, run_agent
from app.db import SessionLocal
from app.models import AgentRun, Contract, PaymentReport
from app.services import finance_model
from app.services.common import today
from app.services.finance_model import Flow
from app.worker.runner import run_once
from tests.helpers import RUB, buyer_session, create_car, signed_deal

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_reserve_and_free_cash(admin):
    signed_deal(admin, contract_date=today() - timedelta(days=70))  # просрочено 700 000 (70, 40 и 10 дней)
    pos = admin.get("/api/admin/finance/position").json()
    assert pos["free_cash_kopecks"] is None and any("Остаток" in w for w in pos["warnings"])
    assert any("Методика резерва" in w for w in pos["warnings"])
    assert not pos["reserve"]["taxes_known"]

    pos = admin.post("/api/admin/finance/cash", json={"as_of": today().isoformat(),
                                                      "amount_kopecks": 2_000_000 * RUB}).json()
    bad = next(i for i in pos["reserve"]["items"] if i["code"] == "bad_debt")
    # по умолчанию: 31–90 дн. — 30% от 600 000; до 30 дн. — 10% от 50 000 + 10% от 50 000 (10 и 40 дн.)
    assert bad["amount_kopecks"] > 0
    assert pos["free_cash_kopecks"] == 2_000_000 * RUB - pos["reserve"]["total_kopecks"]

    pos = admin.put("/api/admin/finance/reserve-policy", json={"opex_months": 2, "aging_0_30": 0, "aging_31_90": 50,
                                                               "aging_90_plus": 100}).json()
    assert not any("Методика резерва" in w for w in pos["warnings"])
    assert pos["policy"]["aging"]["31_90"] == 50


def test_finance_model_formulas():
    start = date(2026, 11, 1)
    flows = [Flow("A", date(2026, 12, 15), 100), Flow("A", date(2027, 1, 15), 100), Flow("B", date(2026, 12, 20), 50)]
    delay = finance_model.scenario_delay(flows, {"A"}, 2, start, 6)
    assert delay["base_total_kopecks"] == delay["scenario_total_kopecks"] == 250
    assert delay["rows"][1]["scenario_kopecks"] == 50 and delay["rows"][3]["scenario_kopecks"] == 100

    defaults = finance_model.scenario_defaults(flows, {"A"}, date(2027, 1, 1), start, 6)
    assert defaults["lost_total_kopecks"] == 100 and defaults["diff_total_kopecks"] == -100

    monthly = finance_model.forecast(flows, start, 6)
    car = finance_model.scenario_next_car(100, 300, 0, monthly)
    assert car["shortfall_kopecks"] == 200 and car["covered_in"] == "2027-01"
    assert finance_model.scenario_next_car(None, 300, 0, monthly)["shortfall_kopecks"] is None

    deals = finance_model.scenario_deals([{"purchase_kopecks": 1000, "sale_kopecks": 1400, "down_kopecks": 400,
                                           "term_months": 10}], start, 12)
    assert deals["total_markup_kopecks"] == 400 and deals["max_cash_need_kopecks"] == 600
    assert deals["payback_month"] == "2027-05"  # −600 + 6 × 100

    res = finance_model.reserve({}, 1000, [(100, 10), (200, 45), (300, 120)], None)
    assert [i["amount_kopecks"] for i in res["items"]] == [0, 3000, 10 + 60 + 180]


def test_scenarios_api_are_labelled_forecasts(admin):
    _, _, contract = signed_deal(admin)
    r = admin.post("/api/admin/finance/scenario", json={"kind": "delay", "contracts": [contract["number"]],
                                                        "delay_months": 1}).json()
    # Сдвиг на месяц: последний платёж горизонта уходит за его пределы, внутри — суммы переносятся
    assert r["label"] == "ПРОГНОЗ" and len(r["rows"]) == 12 and r["diff_total_kopecks"] <= 0
    assert r["rows"][0]["scenario_kopecks"] < r["rows"][0]["base_kopecks"]
    r = admin.post("/api/admin/finance/scenario", json={"kind": "deals", "deals": [
        {"purchase_kopecks": 100, "sale_kopecks": 50, "down_kopecks": 60, "term_months": 2}]})
    assert r.status_code == 422


def test_profitability_by_real_contracts(admin):
    signed_deal(admin)
    data = admin.get("/api/admin/finance/profitability").json()
    make = data["groups"]["Марка"][0]
    assert make["group"] == "Марка: Toyota" and make["markup_kopecks"] == 400_000 * RUB
    assert make["markup_percent"] == 33.3


def test_car_checklist_with_sources_and_evidence(admin):
    car = create_car(admin)
    data = admin.get(f"/api/admin/cars/{car['id']}/checks").json()
    assert data["state"] == "incomplete" and data["missing_required"] == 7
    r = admin.post(f"/api/admin/cars/{car['id']}/checks", data={"item_code": "pledge_registry", "status": "ok",
                                                                "source": ""})
    assert r.status_code == 422  # без источника результат не принимается
    for item in ("vin_match", "title_documents", "seller_identity", "gibdd_registration", "gibdd_wanted",
                 "gibdd_restrictions"):
        admin.post(f"/api/admin/cars/{car['id']}/checks", data={"item_code": item, "status": "ok",
                                                                "source": "Госавтоинспекция / документы"})
    r = admin.post(f"/api/admin/cars/{car['id']}/checks",
                   data={"item_code": "pledge_registry", "status": "problem", "source": "Реестр уведомлений о залоге",
                         "reference": "запрос от сегодня"}, files={"file": ("p.png", PNG, "image/png")})
    data = r.json()
    assert data["state"] == "problem" and "не проводить" in data["verdict"]
    item = next(i for i in data["items"] if i["code"] == "pledge_registry")
    assert item["has_evidence"]
    assert admin.get(f"/api/admin/cars/{car['id']}/checks/{item['check_id']}/evidence").content == PNG


class _Sneaky(Agent):
    code, title, permissions = "sneaky", "Тест", []

    def run(self, db, ctx):
        contract = db.scalar(select(Contract))
        contract.sale_price_kopecks = 1  # попытка изменить договор
        db.flush()
        ctx.create_task("x", "нельзя", "", "", "sneaky")  # действие без разрешения
        return [Finding("info", "не дойдёт")]


def test_agent_cannot_change_data_or_exceed_permissions(admin):
    _, _, contract = signed_deal(admin)
    run = run_agent(_Sneaky())
    assert run.status == "failed" and "не разрешено" in run.error
    with SessionLocal() as db:
        assert db.get(Contract, uuid.UUID(contract["id"])).sale_price_kopecks == 1_600_000 * RUB


def test_agents_produce_findings_with_sources_and_tasks(admin):
    _, client, contract = signed_deal(admin, contract_date=today() - timedelta(days=40))
    buyer = buyer_session(admin, client["id"])
    buyer.post(f"/api/client/contracts/{contract['id']}/payment-reports",
               json={"amount_kopecks": 600_000 * RUB, "paid_on": today().isoformat()})
    with SessionLocal() as db:
        report = db.scalar(select(PaymentReport))
        report.created_at = datetime.now(UTC) - timedelta(days=3)
        db.commit()

    payments = admin.post("/api/admin/agents/payments/run").json()
    assert payments["status"] == "ok" and payments["actions"][0]["action"] == "create_task"
    assert any("не сверено" in f["title"] for f in payments["findings"])

    legal = admin.post("/api/admin/agents/legal/run").json()
    sale = next(f for f in legal["findings"] if "Договор купли-продажи" in f["title"])
    assert "Требуется проверка" in sale["title"] and "юриста" in sale["title"] and "legal.gk.489" in sale["refs"]

    notifications = admin.post("/api/admin/agents/notifications/run").json()
    assert any(f["title"].startswith("Нет разрешённого канала") for f in notifications["findings"])

    accounting = admin.post("/api/admin/agents/accounting/run").json()
    assert any("Налоговый режим не выбран" in f["title"] for f in accounting["findings"])

    management = admin.post("/api/admin/agents/management/run").json()
    assert management["actions"][0]["action"] == "notify_staff"
    assert any(n["title"].startswith("Сводка на") for n in admin.get("/api/admin/notifications").json())

    listing = admin.get("/api/admin/agents").json()
    assert len(listing["agents"]) == 8 and listing["mode"].startswith("Проверяемые правила")


def test_worker_runs_all_agents_daily():
    now = datetime.combine(today(), time(5, 0), tzinfo=UTC)  # 08:00 по Москве — после времени запуска агентов
    run_once(now)
    with SessionLocal() as db:
        codes = {r.agent_code for r in db.scalars(select(AgentRun))}
    assert len(codes) == 8
