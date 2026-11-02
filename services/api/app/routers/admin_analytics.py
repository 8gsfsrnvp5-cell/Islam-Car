"""Расширенная аналитика и выгрузки в Excel (XLSX)."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import BankTransaction, Contract, ContractStatus, Payment
from app.routers.admin_core import CONTRACT_STATUS_RU, PAYMENT_METHOD_RU
from app.security import Actor, require
from app.services import analytics
from app.services.common import today
from app.services.contracts import ledger_for
from app.services.export import Money, Percent, Sheet, xlsx_response

router = APIRouter(prefix="/api/admin", tags=["admin: analytics"])

SOURCE_RU = {"staff": "Сотрудник", "bank_statement": "Банковская выписка", "provider": "Онлайн-оплата"}
TX_STATUS_RU = {"new": "Ждёт решения", "suggested": "Предложен договор", "confirmed": "Учтено",
                "ignored": "Не относится к договорам"}


@router.get("/analytics")
def get_analytics(months: int = Query(12, ge=3, le=36), actor: Actor = Depends(require("reports.read")),
                  db: Session = Depends(get_db)):
    return analytics.build(db, months, actor.can("finance.read"))


@router.get("/analytics.xlsx")
def analytics_xlsx(months: int = Query(12, ge=3, le=36), actor: Actor = Depends(require("reports.read")),
                   db: Session = Depends(get_db)):
    a = analytics.build(db, months, actor.can("finance.read"))
    k = a["kpi"]
    summary = Sheet("Сводка", ["Показатель", "Значение"], [
        ["Дата отчёта", a["today"]],
        ["Дебиторская задолженность, ₽", Money(k["receivables_kopecks"])],
        ["Просрочено, ₽", Money(k["overdue_kopecks"])],
        ["Доля просрочки", Percent(k["overdue_share"])],
        ["Собираемость за 3 закрытых месяца", Percent(k["collection_rate_3m"])],
        ["Договоров с просрочкой", k["contracts_overdue"]],
        ["Заявок за период", k["applications"]],
        ["Конверсия заявок в договор", Percent(k["conversion"])],
    ], notes=a["notes"])
    monthly = Sheet("План и факт", ["Месяц", "По графику, ₽", "Поступило, ₽", "Собираемость",
                                    *[f"{title}, ₽" for title in SOURCE_RU.values()]],
                    [[m["month"], Money(m["planned_kopecks"]), Money(m["collected_kopecks"]),
                      Percent(m["collection_rate"]), *[Money(m["by_source"][s]) for s in SOURCE_RU]]
                     for m in a["monthly"]])
    with_markup = actor.can("finance.read")
    sales = Sheet("Продажи", ["Месяц", "Договоров", "Объём, ₽", *(["Наценка, ₽"] if with_markup else [])],
                  [[s["month"], s["count"], Money(s["volume_kopecks"]),
                    *([Money(s["markup_kopecks"])] if with_markup else [])] for s in a["sales"]])
    aging = Sheet("Просрочка", ["Срок просрочки", "Сумма, ₽", "Договоров (по самой старой просрочке)"],
                  [[b["title"], Money(b["amount_kopecks"]), b["contracts"]] for b in a["aging"]])
    funnel = Sheet("Заявки", ["Этап", "Количество", "Доля от всех заявок"],
                   [[f["title"], f["count"], Percent(f["share"])] for f in a["funnel"]]
                   + [["Закрыты без договора", a["applications_closed_without_deal"], Percent(None)]])
    fc = a["forecast"]
    forecast = Sheet("Прогноз", ["Месяц", "По графику, ₽", "С учётом риска, ₽"],
                     [[r["month"], Money(r["scheduled_kopecks"]), Money(r["risk_adjusted_kopecks"])]
                      for r in fc["rows"]]
                     + [["Возможное погашение просрочки", Money(fc["overdue_recovery_kopecks"]), None]],
                     notes=[f"{fc['label']}. {fc['note']}", fc["method"], *fc["warnings"]])
    return xlsx_response([summary, monthly, sales, aging, funnel, forecast], f"analytics-{today()}.xlsx")


@router.get("/reports/contracts.xlsx")
def contracts_xlsx(actor: Actor = Depends(require("reports.read")), db: Session = Depends(get_db)):
    sheet = Sheet("Договоры", ["Номер", "Статус", "Покупатель", "Автомобиль", "VIN", "Дата подписания", "Цена, ₽",
                               "Закупка, ₽", "Наценка, ₽", "Взнос, ₽", "Срок, мес.", "Оплачено, ₽", "Остаток, ₽",
                               "Просрочено, ₽"])
    live = select(Contract).where(Contract.status.in_([ContractStatus.signed, ContractStatus.completed]))
    for c in db.scalars(live.order_by(Contract.signed_at)):
        lg = ledger_for(db, c)
        sheet.rows.append([c.number, CONTRACT_STATUS_RU[c.status.value], c.client.full_name,
                           f"{c.car.make} {c.car.model} {c.car.year}", c.car.vin or "", c.signed_at,
                           Money(c.sale_price_kopecks), Money(c.purchase_price_kopecks), Money(c.markup_kopecks),
                           Money(c.down_payment_kopecks), c.term_months, Money(lg.paid_kopecks),
                           Money(lg.outstanding_kopecks), Money(lg.overdue_kopecks)])
    return xlsx_response([sheet], "contracts.xlsx")


@router.get("/reports/payments.xlsx")
def payments_xlsx(date_from: date | None = None, date_to: date | None = None,
                  actor: Actor = Depends(require("reports.read")), db: Session = Depends(get_db)):
    stmt = select(Payment, Contract).join(Contract, Contract.id == Payment.contract_id).order_by(Payment.received_on)
    if date_from:
        stmt = stmt.where(Payment.received_on >= date_from)
    if date_to:
        stmt = stmt.where(Payment.received_on <= date_to)
    sheet = Sheet("Платежи", ["Дата поступления", "Договор", "Покупатель", "Сумма, ₽", "Способ", "Документ",
                              "Источник", "Статус", "Причина сторно"])
    for p, c in db.execute(stmt).all():
        sheet.rows.append([p.received_on, c.number, c.client.full_name, Money(p.amount_kopecks),
                           PAYMENT_METHOD_RU[p.method.value], p.document_ref, SOURCE_RU.get(p.source, p.source),
                           "Учтён" if p.status.value == "confirmed" else "Сторнирован", p.reversal_reason])
    return xlsx_response([sheet], "payments.xlsx")


@router.get("/reports/bank.xlsx")
def bank_xlsx(actor: Actor = Depends(require("reports.read")), db: Session = Depends(get_db)):
    numbers = {cid: num for cid, num in db.execute(select(Contract.id, Contract.number))}
    sheet = Sheet("Поступления по выпискам", ["Дата поступления", "П/п №", "Сумма, ₽", "Плательщик",
                                              "Назначение платежа", "Статус", "Договор", "Примечание"])
    for tx in db.scalars(select(BankTransaction).order_by(BankTransaction.received_on)):
        sheet.rows.append([tx.received_on, tx.doc_number, Money(tx.amount_kopecks), tx.payer_name, tx.purpose,
                           TX_STATUS_RU.get(tx.status, tx.status),
                           numbers.get(tx.match_contract_id, "") if tx.status == "confirmed" else "", tx.note])
    return xlsx_response([sheet], "bank-transactions.xlsx")
