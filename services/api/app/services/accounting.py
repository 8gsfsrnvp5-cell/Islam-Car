"""Бухгалтерский модуль: налоговый профиль, утверждённые параметры, журнал операций, расчёты."""

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Car,
    Contract,
    ContractStatus,
    Expense,
    Payment,
    PaymentStatus,
    TaxParam,
    User,
)
from app.services import tax_engine
from app.services.contracts import get_company
from app.services.tax_engine import Param

REGIMES = {
    "individual_ndfl": "Физическое лицо: НДФЛ с продажи имущества",
    "usn_income": "УСН «доходы»",
    "usn_income_expense": "УСН «доходы минус расходы»",
    "osno": "Общая система налогообложения",
}

# Что можно настроить. Значения — только из официального источника, вносит бухгалтер, утверждает владелец.
PARAMS: dict[str, dict] = {
    "usn_income_rate": {"title": "Ставка УСН «доходы»", "unit": "%", "regimes": ["usn_income"],
                        "knowledge": "acc.nk.346_20"},
    "usn_ie_rate": {"title": "Ставка УСН «доходы минус расходы»", "unit": "%", "regimes": ["usn_income_expense"],
                    "knowledge": "acc.nk.346_20"},
    "usn_min_tax_rate": {"title": "Минимальный налог при УСН «доходы минус расходы» (% от доходов)", "unit": "%",
                         "regimes": ["usn_income_expense"], "knowledge": "acc.nk.346_18"},
    "ndfl_rate": {"title": "Ставка НДФЛ с дохода от продажи имущества", "unit": "%", "regimes": ["individual_ndfl"],
                  "knowledge": "acc.nk.224"},
    "ndfl_property_deduction": {"title": "Предельный имущественный вычет при продаже иного имущества", "unit": "руб.",
                                "regimes": ["individual_ndfl"], "knowledge": "acc.nk.220"},
    "ndfl_min_holding_years": {"title": "Минимальный срок владения для освобождения от НДФЛ", "unit": "лет",
                               "regimes": ["individual_ndfl"], "knowledge": "acc.nk.217_1"},
    "vat_rate": {"title": "Ставка НДС, применяемая к межценовой разнице", "unit": "%", "regimes": ["vat"],
                 "knowledge": "acc.nk.164"},
}
TAX_EXPENSE_CATEGORY = "Налоги"


def parse_value(code: str, raw: str) -> Decimal:
    try:
        value = Decimal(raw.replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        raise ValueError("Значение должно быть числом") from None
    if value < 0 or (PARAMS[code]["unit"] == "%" and value > 100):
        raise ValueError("Недопустимое значение")
    return value


def resolve(db: Session, code: str, period_from: date, period_to: date) -> tuple[Param | None, str | None]:
    """Утверждённый параметр, действующий весь период. Если значения менялись внутри периода — расчёт не делается."""
    rows = db.execute(select(TaxParam, User.full_name).join(User, User.id == TaxParam.approved_by).where(
        TaxParam.code == code, TaxParam.status == "approved", TaxParam.effective_from <= period_to)).all()
    covering = [(p, who) for p, who in rows if p.effective_to is None or p.effective_to >= period_from]
    if not covering:
        return None, None
    if len(covering) > 1 or covering[0][0].effective_from > period_from:
        return None, (f"«{PARAMS[code]['title']}»: значение менялось внутри периода — "
                      "выберите период без изменения ставки")
    p, who = covering[0]
    return Param(code=code, value=parse_value(code, p.value), effective_from=p.effective_from,
                 effective_to=p.effective_to, source_url=p.source_url, knowledge_code=PARAMS[code]["knowledge"],
                 approved_by=who), None


def operations(db: Session, period_from: date, period_to: date) -> dict:
    """Журнал денежных операций периода с классификацией — исходные данные для расчётов."""
    receipts = [{"date": p.received_on, "contract": c.number, "amount_kopecks": p.amount_kopecks,
                 "kind": "down_payment_or_installment", "document": p.document_ref}
                for p, c in db.execute(select(Payment, Contract)
                                       .join(Contract, Contract.id == Payment.contract_id).where(
                    Payment.status == PaymentStatus.confirmed, Payment.received_on >= period_from,
                    Payment.received_on <= period_to).order_by(Payment.received_on)).all()]
    expenses = [{"date": e.spent_on, "category": e.category, "amount_kopecks": e.amount_kopecks,
                 "description": e.description, "document": e.document_ref, "car_id": e.car_id}
                for e in db.scalars(select(Expense)
                                    .where(Expense.spent_on >= period_from, Expense.spent_on <= period_to)
                                    .order_by(Expense.spent_on))]
    purchases = [{"date": c.purchase_date, "car": f"{c.make} {c.model} {c.vin or ''}".strip(),
                  "amount_kopecks": c.purchase_price_kopecks or 0, "purchased_from": c.purchased_from,
                  "document": c.purchase_document}
                 for c in db.scalars(select(Car).where(Car.purchase_date >= period_from, Car.purchase_date <= period_to,
                                                       Car.purchase_price_kopecks.is_not(None)))]
    sales = [{"number": c.number, "signed_at": c.signed_at, "price": c.sale_price_kopecks,
              "cost": c.purchase_price_kopecks, "markup": c.markup_kopecks, "purchased_from": c.car.purchased_from,
              "purchase_date": c.car.purchase_date, "car_paid_before_sale": bool(c.car.purchase_date and
                                                                                c.car.purchase_date <= period_to)}
             for c in db.scalars(select(Contract).where(
                 Contract.status.in_([ContractStatus.signed, ContractStatus.completed]),
                 Contract.signed_at >= period_from, Contract.signed_at <= period_to))]
    return {"receipts": receipts, "expenses": expenses, "purchases": purchases, "sales": sales,
            "totals": {"receipts": sum(r["amount_kopecks"] for r in receipts),
                       "expenses": sum(e["amount_kopecks"] for e in expenses),
                       "purchases": sum(p["amount_kopecks"] for p in purchases),
                       "sales_price": sum(s["price"] for s in sales), "sales_markup": sum(s["markup"] for s in sales)}}


def result_dict(r: tax_engine.Result) -> dict:
    return {"code": r.code, "title": r.title, "status": r.status, "amount_kopecks": r.amount_kopecks, "steps": r.steps,
            "params": r.params, "warnings": r.warnings, "basis": r.basis, "inputs_count": {
                k: len(v) for k, v in r.inputs.items() if isinstance(v, list)}}


def calculate(db: Session, period_from: date, period_to: date) -> dict:
    co = get_company(db)
    ops = operations(db, period_from, period_to)
    regime = co.tax_regime
    warnings: list[str] = []
    results: list[tax_engine.Result] = []

    def param(code: str) -> Param | None:
        p, issue = resolve(db, code, period_from, period_to)
        if issue:
            warnings.append(issue)
        return p

    if not regime:
        warnings.append("Налоговый режим не выбран в профиле — расчёт невозможен.")
    elif regime == "osno":
        warnings.append("Общая система налогообложения в этой версии не рассчитывается — требуется бухгалтер.")
    elif regime == "usn_income":
        results.append(tax_engine.usn_income(ops["totals"]["receipts"], ops["receipts"], param("usn_income_rate")))
    elif regime == "usn_income_expense":
        car_costs = [{"date": s["signed_at"], "category": "Стоимость проданного автомобиля",
                      "amount_kopecks": s["cost"],
                      "description": f"Договор № {s['number']}"} for s in ops["sales"] if s["car_paid_before_sale"]]
        opex = [e for e in ops["expenses"] if e["category"] != TAX_EXPENSE_CATEGORY]
        results.append(tax_engine.usn_income_expense(ops["totals"]["receipts"], ops["receipts"], car_costs + opex,
                                                     param("usn_ie_rate"), param("usn_min_tax_rate")))
    elif regime == "individual_ndfl":
        received: dict[str, int] = {}
        for r in ops["receipts"]:
            received[r["contract"]] = received.get(r["contract"], 0) + r["amount_kopecks"]
        sales = []
        for c in db.scalars(select(Contract).where(Contract.number.in_(list(received)))):
            sales.append({"number": c.number, "price": c.sale_price_kopecks, "cost": c.purchase_price_kopecks,
                          "purchase_date": c.car.purchase_date, "sale_date": c.signed_at or c.contract_date,
                          "received_in_period": received[c.number]})
        results.append(tax_engine.ndfl_property(sales, param("ndfl_rate"), param("ndfl_property_deduction"),
                                                param("ndfl_min_holding_years")))
    if regime in ("usn_income", "usn_income_expense", "osno"):
        results.append(tax_engine.vat_margin(ops["sales"], co.vat_payer, param("vat_rate") if co.vat_payer else None))

    for r in results:
        if r.status == "not_configured":
            warnings.append(f"{r.title}: не рассчитан — нет утверждённых параметров.")
    return {
        "period": {"from": period_from, "to": period_to}, "regime": regime, "regime_title": REGIMES.get(regime, ""),
        "vat_payer": co.vat_payer, "results": [result_dict(r) for r in results], "operations_totals": ops["totals"],
        "warnings": warnings,
        "not_included": ["страховые взносы", "налоги с заработной платы", "налог на имущество и транспортный налог",
                         "авансовые платежи и ранее уплаченные суммы"],
        "disclaimer": "Расчёт для проверки бухгалтером, а не налоговая декларация. Подача отчётности и уплата налогов "
                      "системой не выполняются — только через законную интеграцию и с подтверждения владельца.",
    }


def tax_reserve_estimate(db: Session, year_start: date, today: date) -> tuple[int | None, list[str]]:
    """Оценка налога с начала года минус уплаченные налоги (расходы категории «Налоги»).

    None — правила не утверждены, резерв на налоги не определён.
    """
    calc = calculate(db, year_start, today)
    amounts = [r["amount_kopecks"] for r in calc["results"] if r["status"] == "ok" and r["amount_kopecks"] is not None]
    if not amounts or any(r["status"] == "not_configured" for r in calc["results"]) or not calc["results"]:
        return None, calc["warnings"] or ["Нет расчёта налога по утверждённым правилам"]
    paid = sum(e.amount_kopecks for e in db.scalars(select(Expense).where(
        Expense.category == TAX_EXPENSE_CATEGORY, Expense.spent_on >= year_start, Expense.spent_on <= today)))
    return max(sum(amounts) - paid, 0), calc["warnings"]
