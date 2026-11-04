"""Показатели главного экрана.

Разделяются строго: договорной объём (не деньги), поступившие деньги (касса),
дебиторская задолженность (ещё не получено), торговая наценка (не прибыль)
и оценочный результат (управленческая оценка, не бухгалтерская прибыль).
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Application,
    ApplicationStatus,
    Car,
    CarStatus,
    Client,
    Contract,
    ContractStatus,
    Expense,
    OwnershipStatus,
    Payment,
    PaymentReport,
    PaymentReportStatus,
    PaymentStatus,
    SupportThread,
    ThreadStatus,
)
from app.security import Actor
from app.services.common import today
from app.services.ledger import LedgerSummary, compute_ledger

LIVE = (ContractStatus.signed, ContractStatus.completed)


def live_ledgers(db: Session, on: date) -> list[tuple[Contract, LedgerSummary]]:
    contracts = db.scalars(
        select(Contract).where(Contract.status.in_(LIVE))
        .options(selectinload(Contract.schedule), selectinload(Contract.client), selectinload(Contract.car))
    ).all()
    paid = dict(db.execute(
        select(Payment.contract_id, func.sum(Payment.amount_kopecks))
        .where(Payment.status == PaymentStatus.confirmed).group_by(Payment.contract_id)).all())
    result = []
    for c in contracts:
        items = [(i.seq, i.kind.value, i.due_date, i.amount_kopecks) for i in c.schedule]
        result.append((c, compute_ledger(items, int(paid.get(c.id, 0) or 0), on)))
    return result


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def build_dashboard(db: Session, actor: Actor, period_from: date | None, period_to: date | None) -> dict[str, Any]:
    t = today()
    p_from = period_from or month_start(t)
    p_to = period_to or (add_month(month_start(t)) - timedelta(days=1))
    ledgers = live_ledgers(db, t)

    receivables = sum(lg.outstanding_kopecks for _, lg in ledgers if _.status == ContractStatus.signed)
    overdue = sum(lg.overdue_kopecks for _, lg in ledgers)
    horizon = t + timedelta(days=30)
    upcoming_30 = sum(r.remaining_kopecks for _, lg in ledgers for r in lg.rows
                      if r.remaining_kopecks > 0 and t <= r.due_date <= horizon)
    down_received = sum(r.paid_kopecks for _, lg in ledgers for r in lg.rows if r.kind == "down_payment")

    forecast: dict[date, int] = defaultdict(int)
    first_month = month_start(t)
    months = [first_month]
    for _ in range(5):
        months.append(add_month(months[-1]))
    for _, lg in ledgers:
        for r in lg.rows:
            if r.remaining_kopecks > 0 and r.status != "overdue" and month_start(r.due_date) in months:
                forecast[month_start(r.due_date)] += r.remaining_kopecks

    cash_period = db.scalar(
        select(func.coalesce(func.sum(Payment.amount_kopecks), 0))
        .where(Payment.status == PaymentStatus.confirmed, Payment.received_on >= p_from,
               Payment.received_on <= p_to)) or 0

    problem = sorted(
        ({"contract_id": c.id, "number": c.number, "client": c.client.full_name,
          "car": f"{c.car.make} {c.car.model}", "overdue_kopecks": lg.overdue_kopecks,
          "overdue_items": lg.overdue_items, "oldest_overdue_date": lg.oldest_overdue_date,
          "days_overdue": (t - lg.oldest_overdue_date).days if lg.oldest_overdue_date else 0}
         for c, lg in ledgers if lg.overdue_kopecks > 0),
        key=lambda x: -x["days_overdue"])

    count = lambda stmt: db.scalar(select(func.count()).select_from(stmt.subquery())) or 0  # noqa: E731
    data: dict[str, Any] = {
        "today": t,
        "period": {"from": p_from, "to": p_to},
        "operations": {
            "clients": count(select(Client.id)),
            "active_contracts": sum(1 for c, _ in ledgers if c.status == ContractStatus.signed),
            "completed_contracts": sum(1 for c, _ in ledgers if c.status == ContractStatus.completed),
            "draft_contracts": count(select(Contract.id).where(Contract.status == ContractStatus.draft)),
            "cars_sold": len(ledgers),
            "cars_in_stock": count(select(Car.id).where(
                Car.ownership_status == OwnershipStatus.owned,
                Car.status.in_([CarStatus.available, CarStatus.reserved, CarStatus.draft]))),
            "cars_purchasing": count(select(Car.id).where(
                Car.ownership_status == OwnershipStatus.purchasing, Car.status != CarStatus.archived)),
            "new_applications": count(select(Application.id).where(Application.status == ApplicationStatus.new)),
            "pending_payment_reports": count(select(PaymentReport.id).where(
                PaymentReport.status == PaymentReportStatus.pending)),
            "open_threads": count(select(SupportThread.id).where(SupportThread.status == ThreadStatus.open)),
            "problem_deals": len(problem),
        },
        "money": {
            "contracted_volume_kopecks": sum(c.sale_price_kopecks for c, _ in ledgers),
            "down_payments_contracted_kopecks": sum(c.down_payment_kopecks for c, _ in ledgers),
            "down_payments_received_kopecks": down_received,
            "receivables_kopecks": receivables,
            "overdue_kopecks": overdue,
            "cash_received_period_kopecks": cash_period,
            "upcoming_30d_kopecks": upcoming_30,
            "forecast": [{"month": m, "expected_kopecks": forecast.get(m, 0)} for m in months],
        },
        "problem_deals": problem[:10],
    }

    if actor.can("finance.read"):
        opex = db.scalar(select(func.coalesce(func.sum(Expense.amount_kopecks), 0))
                         .where(Expense.spent_on >= p_from, Expense.spent_on <= p_to)) or 0
        markup_period = sum(c.markup_kopecks for c, _ in ledgers
                            if c.signed_at and p_from <= c.signed_at <= p_to)
        inventory = db.scalar(select(func.coalesce(func.sum(Car.purchase_price_kopecks), 0)).where(
            Car.ownership_status == OwnershipStatus.owned,
            Car.status.in_([CarStatus.available, CarStatus.reserved, CarStatus.draft]))) or 0
        data["finance"] = {
            "purchase_cost_sold_kopecks": sum(c.purchase_price_kopecks for c, _ in ledgers),
            "gross_markup_kopecks": sum(c.markup_kopecks for c, _ in ledgers),
            "inventory_cost_kopecks": inventory,
            "operating_expenses_period_kopecks": opex,
            "markup_signed_in_period_kopecks": markup_period,
            "estimated_result_period_kopecks": markup_period - opex,
            "estimated_result_note": ("Оценка: наценка по договорам, подписанным в периоде, минус расходы периода. "
                                      "Не является бухгалтерской или налоговой прибылью и не равна деньгам на счёте."),
            "taxes": {"status": "not_configured",
                      "message": "Налоговые обязательства не рассчитываются: нет утверждённых налоговых правил "
                                 "(бухгалтерский модуль — версия 3). Значения не выдумываются."},
        }
    return data
