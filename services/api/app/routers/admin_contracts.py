"""Договоры, график, платежи, сообщения об оплате, расходы, результат по автомобилям."""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Car,
    CarStatus,
    Client,
    Contract,
    ContractStatus,
    Expense,
    OwnershipStatus,
    Payment,
    PaymentMethod,
    PaymentReport,
    PaymentReportStatus,
    PaymentStatus,
)
from app.schemas import (
    ContractIn,
    ContractPatch,
    ExpenseIn,
    PaymentIn,
    PreviewIn,
    ReportReviewIn,
    ReverseIn,
    SignIn,
)
from app.security import Actor, require
from app.serializers import contract_staff, payment_dict, report_dict
from app.services import audit
from app.services.common import today
from app.services.contracts import (
    apply_terms,
    get_company,
    is_consumer_deal,
    ledger_for,
    run_checks,
    sign,
    sync_completion,
    terms_of,
)
from app.services.dashboard import live_ledgers
from app.services.notify import notify_client, rub
from app.services.schedule import Terms, TermsError, build_schedule

router = APIRouter(prefix="/api/admin", tags=["admin: contracts"])

LIVE = (ContractStatus.signed, ContractStatus.completed)


def get_contract(db: Session, contract_id: uuid.UUID) -> Contract:
    c = db.get(Contract, contract_id)
    if not c:
        raise HTTPException(404, "Договор не найден")
    return c


def checks_dict(report) -> dict:
    return {"can_sign": report.can_sign, "items": [
        {"code": c.code, "ok": c.ok, "message": c.message, "blocking": c.blocking, "info": c.info}
        for c in report.checks]}


def contract_full(db: Session, c: Contract, actor: Actor) -> dict:
    data = contract_staff(c, ledger_for(db, c), actor)
    data["schedule"] = [{"seq": i.seq, "kind": i.kind, "due_date": i.due_date, "amount_kopecks": i.amount_kopecks}
                        for i in c.schedule]
    data["payments"] = [payment_dict(p) for p in c.payments]
    data["reports"] = [report_dict(r) for r in db.scalars(
        select(PaymentReport).where(PaymentReport.contract_id == c.id).order_by(PaymentReport.created_at.desc()))]
    if c.status == ContractStatus.draft:
        data["checks"] = checks_dict(run_checks(db, c))
    return data


def sellable_car(db: Session, car_id: uuid.UUID) -> Car:
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Автомобиль не найден")
    if car.status in (CarStatus.sold, CarStatus.archived):
        raise HTTPException(409, "Автомобиль продан или в архиве")
    if car.purchase_price_kopecks is None:
        raise HTTPException(422, "В карточке автомобиля не указана закупочная стоимость")
    return car


def terms_from(data, car: Car) -> Terms:
    return Terms(car.purchase_price_kopecks, data.sale_price_kopecks, data.down_payment_kopecks,
                 data.term_months, data.contract_date, data.first_payment_date)


@router.get("/contracts")
def list_contracts(status: ContractStatus | None = None, actor: Actor = Depends(require("contracts.read")),
                   db: Session = Depends(get_db)):
    stmt = select(Contract).order_by(Contract.created_at.desc()).limit(500)
    if status:
        stmt = stmt.where(Contract.status == status)
    return [contract_staff(c, ledger_for(db, c) if c.status in LIVE else None, actor, with_rows=False)
            for c in db.scalars(stmt).all()]


@router.post("/contracts/preview")
def preview(data: PreviewIn, actor: Actor = Depends(require("contracts.write")), db: Session = Depends(get_db)):
    """Расчёт условий и графика без сохранения."""
    car = sellable_car(db, data.car_id)
    t = terms_from(data, car)
    try:
        items = build_schedule(t)
    except TermsError as e:
        raise HTTPException(422, str(e)) from None
    result = {
        "sale_price_kopecks": t.sale_price_kopecks, "down_payment_kopecks": t.down_payment_kopecks,
        "financed_kopecks": t.financed_kopecks, "term_months": t.term_months,
        "monthly_payment_kopecks": next(i.amount_kopecks for i in items if i.kind == "installment"),
        "schedule": [{"seq": i.seq, "kind": i.kind, "due_date": i.due_date, "amount_kopecks": i.amount_kopecks}
                     for i in items],
        "car_owned": car.ownership_status == OwnershipStatus.owned,
    }
    if actor.can("finance.read"):
        result["purchase_price_kopecks"] = t.purchase_price_kopecks
        result["markup_kopecks"] = t.markup_kopecks
    return result


@router.post("/contracts", status_code=201)
def create_contract(data: ContractIn, actor: Actor = Depends(require("contracts.write")),
                    db: Session = Depends(get_db)):
    client = db.get(Client, data.client_id)
    if not client:
        raise HTTPException(404, "Клиент не найден")
    car = sellable_car(db, data.car_id)
    open_draft = db.scalar(select(Contract.id).where(Contract.car_id == car.id,
                                                     Contract.status == ContractStatus.draft))
    if open_draft:
        raise HTTPException(409, "На этот автомобиль уже есть черновик договора")
    regime = get_company(db).seller_regime
    c = Contract(client_id=client.id, car_id=car.id, application_id=data.application_id, seller_regime=regime,
                 buyer_type=client.party_type, is_consumer_deal=is_consumer_deal(regime, client.party_type),
                 disclose_cost_to_buyer=data.disclose_cost_to_buyer, notes=data.notes, created_by=actor.user.id)
    try:
        apply_terms(c, terms_from(data, car))
    except TermsError as e:
        raise HTTPException(422, str(e)) from None
    db.add(c)
    if car.status == CarStatus.available:
        car.status = CarStatus.reserved
    db.flush()
    audit.record(db, actor, "contract.draft_created", "contract", c.id, client=client.id, car=car.id,
                 sale_price=c.sale_price_kopecks, down=c.down_payment_kopecks, term=c.term_months)
    db.commit()
    db.refresh(c)
    return contract_full(db, c, actor)


@router.get("/contracts/{contract_id}")
def read_contract(contract_id: uuid.UUID, actor: Actor = Depends(require("contracts.read")),
                  db: Session = Depends(get_db)):
    return contract_full(db, get_contract(db, contract_id), actor)


@router.patch("/contracts/{contract_id}")
def update_draft(contract_id: uuid.UUID, data: ContractPatch, actor: Actor = Depends(require("contracts.write")),
                 db: Session = Depends(get_db)):
    c = get_contract(db, contract_id)
    if c.status != ContractStatus.draft:
        raise HTTPException(409, "Подписанный договор не изменяется. Изменения — только дополнительным соглашением.")
    changes = data.model_dump(exclude_unset=True)
    current = terms_of(c)
    t = Terms(c.car.purchase_price_kopecks or current.purchase_price_kopecks,
              changes.get("sale_price_kopecks", current.sale_price_kopecks),
              changes.get("down_payment_kopecks", current.down_payment_kopecks),
              changes.get("term_months", current.term_months),
              changes.get("contract_date", current.contract_date),
              changes.get("first_payment_date", current.first_payment_date))
    try:
        apply_terms(c, t)
    except TermsError as e:
        raise HTTPException(422, str(e)) from None
    if "disclose_cost_to_buyer" in changes:
        c.disclose_cost_to_buyer = changes["disclose_cost_to_buyer"]
    if "notes" in changes:
        c.notes = changes["notes"]
    # Тип покупателя и режим продавца могли измениться в карточках — перечитываем
    c.buyer_type = c.client.party_type
    c.seller_regime = get_company(db).seller_regime
    c.is_consumer_deal = is_consumer_deal(c.seller_regime, c.buyer_type)
    audit.record(db, actor, "contract.draft_updated", "contract", c.id, changes=changes)
    db.commit()
    db.refresh(c)
    return contract_full(db, c, actor)


@router.post("/contracts/{contract_id}/sign")
def sign_contract(contract_id: uuid.UUID, data: SignIn, actor: Actor = Depends(require("contracts.sign")),
                  db: Session = Depends(get_db)):
    if not data.confirm_paper_signed:
        raise HTTPException(422, "Подтвердите, что договор подписан обеими сторонами")
    c = get_contract(db, contract_id)
    c.buyer_type = c.client.party_type
    report = sign(db, c, data.signed_on, actor.user.id)
    if not report.can_sign:
        db.rollback()
        raise HTTPException(422, {"message": "Договор не прошёл проверки", "checks": checks_dict(report)})
    audit.record(db, actor, "contract.signed", "contract", c.id, number=c.number, signed_on=data.signed_on)
    notify_client(db, c.client_id, "contract.signed", f"Договор № {c.number} оформлен",
                  "График платежей доступен в личном кабинете.", f"/cabinet/contracts/{c.id}")
    db.commit()
    db.refresh(c)
    return contract_full(db, c, actor)


@router.post("/contracts/{contract_id}/cancel")
def cancel_draft(contract_id: uuid.UUID, actor: Actor = Depends(require("contracts.write")),
                 db: Session = Depends(get_db)):
    c = get_contract(db, contract_id)
    if c.status != ContractStatus.draft:
        raise HTTPException(409, "Отменить можно только черновик")
    c.status = ContractStatus.cancelled
    if c.car.status == CarStatus.reserved:
        c.car.status = CarStatus.available
    audit.record(db, actor, "contract.draft_cancelled", "contract", c.id)
    db.commit()
    return contract_full(db, c, actor)


# --- Платежи ------------------------------------------------------------------

@router.get("/payments")
def list_payments(contract_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
                  actor: Actor = Depends(require("payments.read")), db: Session = Depends(get_db)):
    stmt = select(Payment, Contract).join(Contract, Contract.id == Payment.contract_id) \
        .order_by(Payment.received_on.desc(), Payment.confirmed_at.desc()).limit(1000)
    if contract_id:
        stmt = stmt.where(Payment.contract_id == contract_id)
    if date_from:
        stmt = stmt.where(Payment.received_on >= date_from)
    if date_to:
        stmt = stmt.where(Payment.received_on <= date_to)
    return [{**payment_dict(p), "contract_number": c.number, "client": c.client.full_name}
            for p, c in db.execute(stmt).all()]


@router.post("/payments", status_code=201)
def confirm_payment(data: PaymentIn, actor: Actor = Depends(require("payments.confirm")),
                    db: Session = Depends(get_db)):
    """Подтверждение поступления по банковской выписке или кассовому документу."""
    c = get_contract(db, data.contract_id)
    if c.status not in LIVE:
        raise HTTPException(409, "Платёж можно учесть только по подписанному договору")
    if data.received_on > today():
        raise HTTPException(422, "Дата поступления не может быть в будущем")
    if data.received_on < c.contract_date:
        raise HTTPException(422, "Дата поступления раньше даты договора")
    outstanding = ledger_for(db, c).outstanding_kopecks
    if data.amount_kopecks > outstanding:
        raise HTTPException(422, f"Сумма больше остатка долга ({rub(outstanding)}). Переплату оформите отдельно.")
    dup = db.scalar(select(Payment.id).where(
        Payment.contract_id == c.id, Payment.status == PaymentStatus.confirmed,
        Payment.document_ref == data.document_ref, Payment.method == data.method))
    if dup and data.method == PaymentMethod.bank_transfer:
        raise HTTPException(409, "Платёж с таким номером документа уже учтён")
    report = None
    if data.report_id:
        report = db.get(PaymentReport, data.report_id)
        if not report or report.contract_id != c.id or report.status != PaymentReportStatus.pending:
            raise HTTPException(409, "Сообщение об оплате не найдено или уже обработано")
    if data.corrects_payment_id:
        original = db.get(Payment, data.corrects_payment_id)
        if not original or original.contract_id != c.id or original.status != PaymentStatus.reversed:
            raise HTTPException(409, "Исправлять можно только сторнированный платёж этого договора")

    p = Payment(contract_id=c.id, amount_kopecks=data.amount_kopecks, received_on=data.received_on,
                method=data.method, document_ref=data.document_ref, note=data.note, confirmed_by=actor.user.id,
                report_id=data.report_id, corrects_payment_id=data.corrects_payment_id)
    db.add(p)
    if report:
        report.status = PaymentReportStatus.matched
        report.reviewed_by = actor.user.id
        report.reviewed_at = datetime.now(UTC)
        report.review_note = "Платёж найден и учтён"
    db.flush()
    sync_completion(db, c)
    audit.record(db, actor, "payment.confirmed", "payment", p.id, contract=c.number, amount=p.amount_kopecks,
                 received_on=p.received_on, document=p.document_ref, corrects=data.corrects_payment_id)
    notify_client(db, c.client_id, "payment.confirmed",
                  f"Платёж {rub(p.amount_kopecks)} по договору № {c.number} получен и учтён",
                  "Благодарим за своевременную оплату.", f"/cabinet/contracts/{c.id}")
    if c.status == ContractStatus.completed:
        notify_client(db, c.client_id, "contract.completed", f"Договор № {c.number} полностью оплачен",
                      "Обязательства по оплате исполнены.", f"/cabinet/contracts/{c.id}")
    db.commit()
    return {**payment_dict(p), "ledger_outstanding_kopecks": ledger_for(db, c).outstanding_kopecks,
            "contract_status": c.status}


@router.post("/payments/{payment_id}/reverse")
def reverse_payment(payment_id: uuid.UUID, data: ReverseIn, actor: Actor = Depends(require("payments.reverse")),
                    db: Session = Depends(get_db)):
    """Сторнирование ошибочного платежа. Исходная запись сохраняется навсегда."""
    p = db.get(Payment, payment_id)
    if not p:
        raise HTTPException(404, "Платёж не найден")
    if p.status == PaymentStatus.reversed:
        raise HTTPException(409, "Платёж уже сторнирован")
    p.status = PaymentStatus.reversed
    p.reversed_by = actor.user.id
    p.reversed_at = datetime.now(UTC)
    p.reversal_reason = data.reason
    c = get_contract(db, p.contract_id)
    db.flush()
    sync_completion(db, c)
    audit.record(db, actor, "payment.reversed", "payment", p.id, contract=c.number, amount=p.amount_kopecks,
                 reason=data.reason)
    notify_client(db, c.client_id, "payment.reversed", f"Исправлена запись о платеже по договору № {c.number}",
                  "Актуальный остаток доступен в личном кабинете.", f"/cabinet/contracts/{c.id}")
    db.commit()
    return {**payment_dict(p), "ledger_outstanding_kopecks": ledger_for(db, c).outstanding_kopecks}


@router.get("/payment-reports")
def list_reports(status: PaymentReportStatus | None = PaymentReportStatus.pending,
                 actor: Actor = Depends(require("payments.read")), db: Session = Depends(get_db)):
    stmt = select(PaymentReport, Contract).join(Contract, Contract.id == PaymentReport.contract_id) \
        .order_by(PaymentReport.created_at.desc()).limit(500)
    if status:
        stmt = stmt.where(PaymentReport.status == status)
    return [{**report_dict(r), "contract_number": c.number, "client": c.client.full_name}
            for r, c in db.execute(stmt).all()]


@router.post("/payment-reports/{report_id}/reject")
def reject_report(report_id: uuid.UUID, data: ReportReviewIn, actor: Actor = Depends(require("payments.confirm")),
                  db: Session = Depends(get_db)):
    r = db.get(PaymentReport, report_id)
    if not r or r.status != PaymentReportStatus.pending:
        raise HTTPException(409, "Сообщение не найдено или уже обработано")
    r.status = PaymentReportStatus.rejected
    r.reviewed_by = actor.user.id
    r.reviewed_at = datetime.now(UTC)
    r.review_note = data.note
    c = get_contract(db, r.contract_id)
    notify_client(db, c.client_id, "payment.report_rejected", "Платёж пока не найден",
                  data.note, f"/cabinet/contracts/{c.id}")
    audit.record(db, actor, "payment_report.rejected", "payment_report", r.id, note=data.note)
    db.commit()
    return report_dict(r)


# --- Календарь поступлений ---------------------------------------------------------

@router.get("/calendar")
def calendar(month: str | None = None, actor: Actor = Depends(require("payments.read")),
             db: Session = Depends(get_db)):
    t = today()
    try:
        first = date.fromisoformat(f"{month}-01") if month else t.replace(day=1)
    except ValueError:
        raise HTTPException(422, "Месяц в формате ГГГГ-ММ") from None
    nxt = date(first.year + first.month // 12, first.month % 12 + 1, 1)
    items = []
    for c, lg in live_ledgers(db, t):
        for r in lg.rows:
            if first <= r.due_date < nxt:
                items.append({"contract_id": c.id, "number": c.number, "client": c.client.full_name,
                              "car": f"{c.car.make} {c.car.model}", "seq": r.seq, "kind": r.kind,
                              "due_date": r.due_date, "amount_kopecks": r.amount_kopecks,
                              "paid_kopecks": r.paid_kopecks, "remaining_kopecks": r.remaining_kopecks,
                              "status": r.status})
    items.sort(key=lambda x: (x["due_date"], x["number"] or ""))
    return {"month": first.strftime("%Y-%m"), "today": t, "items": items,
            "expected_kopecks": sum(i["amount_kopecks"] for i in items),
            "received_kopecks": sum(i["paid_kopecks"] for i in items),
            "remaining_kopecks": sum(i["remaining_kopecks"] for i in items)}


# --- Расходы и результат по автомобилям -----------------------------------------

@router.get("/expenses")
def list_expenses(date_from: date | None = None, date_to: date | None = None,
                  actor: Actor = Depends(require("finance.read")), db: Session = Depends(get_db)):
    stmt = select(Expense).order_by(Expense.spent_on.desc()).limit(1000)
    if date_from:
        stmt = stmt.where(Expense.spent_on >= date_from)
    if date_to:
        stmt = stmt.where(Expense.spent_on <= date_to)
    return [{"id": e.id, "spent_on": e.spent_on, "category": e.category, "amount_kopecks": e.amount_kopecks,
             "description": e.description, "car_id": e.car_id, "document_ref": e.document_ref,
             "created_at": e.created_at} for e in db.scalars(stmt).all()]


@router.post("/expenses", status_code=201)
def add_expense(data: ExpenseIn, actor: Actor = Depends(require("expenses.write")), db: Session = Depends(get_db)):
    if data.car_id and not db.get(Car, data.car_id):
        raise HTTPException(404, "Автомобиль не найден")
    e = Expense(**data.model_dump(), created_by=actor.user.id)
    db.add(e)
    db.flush()
    audit.record(db, actor, "expense.created", "expense", e.id, amount=e.amount_kopecks, category=e.category)
    db.commit()
    return {"id": e.id}


@router.get("/finance/cars")
def car_results(actor: Actor = Depends(require("finance.read")), db: Session = Depends(get_db)):
    """Фактический результат по каждому проданному автомобилю (по данным договора и учтённым платежам)."""
    car_expenses = dict(db.execute(select(Expense.car_id, func.sum(Expense.amount_kopecks))
                                   .where(Expense.car_id.is_not(None)).group_by(Expense.car_id)).all())
    rows = []
    for c, lg in live_ledgers(db, today()):
        extra = int(car_expenses.get(c.car_id, 0) or 0)
        rows.append({
            "contract_id": c.id, "number": c.number, "car": f"{c.car.make} {c.car.model}, {c.car.year}",
            "client": c.client.full_name, "purchase_price_kopecks": c.purchase_price_kopecks,
            "sale_price_kopecks": c.sale_price_kopecks, "markup_kopecks": c.markup_kopecks,
            "car_expenses_kopecks": extra, "markup_after_car_expenses_kopecks": c.markup_kopecks - extra,
            "received_kopecks": lg.paid_kopecks, "outstanding_kopecks": lg.outstanding_kopecks,
            "overdue_kopecks": lg.overdue_kopecks,
            # Сколько вложенных в автомобиль денег уже вернулось
            "cost_recovered_kopecks": min(lg.paid_kopecks, c.purchase_price_kopecks + extra),
        })
    return rows
