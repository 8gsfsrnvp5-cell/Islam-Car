"""Финансовое положение, резерв, свободные деньги, сценарии, рентабельность."""

from collections import defaultdict
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CashSnapshot, Expense
from app.schemas import StrictModel
from app.security import Actor, require
from app.services import audit, finance_model
from app.services.accounting import TAX_EXPENSE_CATEGORY, tax_reserve_estimate
from app.services.common import today
from app.services.contracts import get_company
from app.services.dashboard import live_ledgers
from app.services.finance_model import Flow
from app.services.schedule import add_months

router = APIRouter(prefix="/api/admin/finance", tags=["admin: finance"])
HORIZON = 12


class CashIn(StrictModel):
    as_of: date
    amount_kopecks: int = Field(ge=-10**13, le=10**13)
    note: str = Field(default="", max_length=500)


class PolicyIn(StrictModel):
    opex_months: float = Field(ge=0, le=24)
    aging_0_30: float = Field(ge=0, le=100)
    aging_31_90: float = Field(ge=0, le=100)
    aging_90_plus: float = Field(ge=0, le=100)


class ScenarioIn(StrictModel):
    kind: Literal["delay", "defaults", "next_car", "deals"]
    contracts: list[str] = Field(default_factory=list)
    delay_months: int = Field(default=1, ge=1, le=24)
    from_month: date | None = None
    purchase_kopecks: int = Field(default=0, ge=0)
    extra_kopecks: int = Field(default=0, ge=0)
    deals: list[dict] = Field(default_factory=list, max_length=20)


def monthly_opex(db: Session, on: date) -> int:
    start = add_months(on.replace(day=1), -3)  # три полных месяца до текущего
    end = on.replace(day=1) - timedelta(days=1)
    total = sum(e.amount_kopecks for e in db.scalars(select(Expense).where(
        Expense.spent_on >= start, Expense.spent_on <= end, Expense.category != TAX_EXPENSE_CATEGORY)))
    return total // 3


def flows_and_overdue(db: Session, on: date) -> tuple[list[Flow], list[tuple[int, int]], list[dict]]:
    flows, overdue, contracts = [], [], []
    for c, lg in live_ledgers(db, on):
        contracts.append({"number": c.number, "client": c.client.full_name,
                          "outstanding_kopecks": lg.outstanding_kopecks})
        for r in lg.rows:
            if r.remaining_kopecks <= 0:
                continue
            if r.status == "overdue":
                overdue.append((r.remaining_kopecks, (on - r.due_date).days))
            else:
                flows.append(Flow(c.number, r.due_date, r.remaining_kopecks))
    return flows, overdue, contracts


def position(db: Session) -> dict:
    on = today()
    co = get_company(db)
    policy = co.reserve_policy or {}
    snapshot = db.scalar(select(CashSnapshot)
                         .order_by(CashSnapshot.as_of.desc(), CashSnapshot.created_at.desc()).limit(1))
    flows, overdue, contracts = flows_and_overdue(db, on)
    tax_due, tax_warnings = tax_reserve_estimate(db, on.replace(month=1, day=1), on)
    opex = monthly_opex(db, on)
    res = finance_model.reserve(policy, opex, overdue, tax_due)
    warnings = []
    if not policy.get("approved_at"):
        warnings.append("Методика резерва — значения по умолчанию, владелец их не утверждал")
    if snapshot is None:
        warnings.append("Остаток денежных средств не внесён — свободные деньги не определены")
    elif (on - snapshot.as_of).days > 7:
        warnings.append(f"Остаток внесён {snapshot.as_of:%d.%m.%Y} — обновите по выписке")
    if not res["taxes_known"]:
        warnings.append("Резерв на налоги не определён: " + "; ".join(tax_warnings[:2]))
    free = snapshot.amount_kopecks - res["total_kopecks"] if snapshot else None
    return {
        "today": on, "cash": {"as_of": snapshot.as_of, "amount_kopecks": snapshot.amount_kopecks, "note": snapshot.note}
        if snapshot else None,
        "reserve": res, "free_cash_kopecks": free, "monthly_opex_kopecks": opex,
        "policy": {**finance_model.DEFAULT_POLICY, **policy},
        "forecast": [{"month": m, "expected_kopecks": v}
                     for m, v in finance_model.forecast(flows, on, HORIZON).items()],
        "contracts": contracts, "warnings": warnings,
        "note": "Свободные деньги = остаток − резерв. Прогноз поступлений — по графикам, без учёта просроченных сумм.",
    }


@router.get("/position")
def get_position(actor: Actor = Depends(require("finance.read")), db: Session = Depends(get_db)):
    data = position(db)
    db.commit()
    return data


@router.post("/cash", status_code=201)
def add_cash(data: CashIn, actor: Actor = Depends(require("expenses.write")), db: Session = Depends(get_db)):
    if data.as_of > today():
        raise HTTPException(422, "Дата остатка не может быть в будущем")
    snap = CashSnapshot(**data.model_dump(), created_by=actor.user.id)
    db.add(snap)
    audit.record(db, actor, "finance.cash_snapshot", "cash", None, as_of=data.as_of, amount=data.amount_kopecks)
    db.commit()
    return position(db)


@router.put("/reserve-policy")
def save_policy(data: PolicyIn, actor: Actor = Depends(require("settings.write")), db: Session = Depends(get_db)):
    co = get_company(db)
    co.reserve_policy = {"opex_months": data.opex_months,
                         "aging": {"0_30": data.aging_0_30, "31_90": data.aging_31_90, "90_plus": data.aging_90_plus},
                         "approved_at": today().isoformat(), "approved_by": actor.user.full_name}
    audit.record(db, actor, "finance.reserve_policy", "settings", "reserve", policy=co.reserve_policy)
    db.commit()
    return position(db)


@router.post("/scenario")
def scenario(data: ScenarioIn, actor: Actor = Depends(require("finance.read")), db: Session = Depends(get_db)):
    """Сценарии — прогнозы для принятия решений, а не фактическая прибыль."""
    on = today()
    flows, _, _ = flows_and_overdue(db, on)
    if data.kind == "delay":
        result = finance_model.scenario_delay(flows, set(data.contracts), data.delay_months, on, HORIZON)
    elif data.kind == "defaults":
        result = finance_model.scenario_defaults(flows, set(data.contracts), data.from_month or on, on, HORIZON)
    elif data.kind == "next_car":
        pos = position(db)
        result = finance_model.scenario_next_car(pos["free_cash_kopecks"], data.purchase_kopecks, data.extra_kopecks,
                                                 finance_model.forecast(flows, on, HORIZON))
    else:
        try:
            deals = [{"purchase_kopecks": int(d["purchase_kopecks"]), "sale_kopecks": int(d["sale_kopecks"]),
                      "down_kopecks": int(d["down_kopecks"]), "term_months": int(d["term_months"])} for d in data.deals]
            result = finance_model.scenario_deals(deals, on, 36)
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, f"Проверьте параметры сделок: {e}") from None
    db.rollback()
    return {"kind": data.kind, "label": "ПРОГНОЗ", **result}


@router.get("/profitability")
def profitability(actor: Actor = Depends(require("finance.read")), db: Session = Depends(get_db)):
    """Какие автомобили и условия дают лучший результат — только по реальным договорам."""
    on = today()

    def term_bucket(n: int) -> str:
        return "до 12 мес." if n <= 12 else "13–24 мес." if n <= 24 else "более 24 мес."

    groups: dict[str, dict] = {}

    def add(key: str, c, lg) -> None:
        g = groups.setdefault(key, {"group": key, "contracts": 0, "price_kopecks": 0, "markup_kopecks": 0,
                                    "received_kopecks": 0, "overdue_kopecks": 0})
        g["contracts"] += 1
        g["price_kopecks"] += c.sale_price_kopecks
        g["markup_kopecks"] += c.markup_kopecks
        g["received_kopecks"] += lg.paid_kopecks
        g["overdue_kopecks"] += lg.overdue_kopecks

    by: dict[str, list] = defaultdict(list)
    for c, lg in live_ledgers(db, on):
        add(f"Марка: {c.car.make}", c, lg)
        add(f"Срок: {term_bucket(c.term_months)}", c, lg)
        down_share = c.down_payment_kopecks / c.sale_price_kopecks if c.sale_price_kopecks else 0
        add(f"Взнос: {'до 30%' if down_share < 0.3 else '30–50%' if down_share <= 0.5 else 'более 50%'}", c, lg)
    for g in groups.values():
        g["markup_percent"] = round(g["markup_kopecks"] / (g["price_kopecks"] - g["markup_kopecks"]) * 100, 1) \
            if g["price_kopecks"] > g["markup_kopecks"] else None
        g["overdue_share"] = round(g["overdue_kopecks"] / g["price_kopecks"] * 100, 1) if g["price_kopecks"] else 0
        by[g["group"].split(":")[0]].append(g)
    return {"groups": {k: sorted(v, key=lambda x: -x["markup_kopecks"]) for k, v in by.items()},
            "note": "Наценка — по условиям договоров; доля просрочки — от цены договоров группы. Это не прибыль."}
