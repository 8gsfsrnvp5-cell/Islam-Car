"""Учёт поступления по договору — единая точка для сотрудника, банковской выписки и платёжного провайдера.

Все пути проходят одни и те же проверки: договор действует, дата не в будущем и не раньше договора,
сумма не больше остатка, один и тот же документ не учитывается дважды.
"""

import uuid
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Contract,
    ContractStatus,
    Payment,
    PaymentMethod,
    PaymentReport,
    PaymentReportStatus,
    PaymentStatus,
)
from app.services.common import today
from app.services.contracts import ledger_for, sync_completion
from app.services.messaging import dispatch_payment_confirmed
from app.services.notify import notify_client, rub

LIVE = (ContractStatus.signed, ContractStatus.completed)


def record_payment(db: Session, c: Contract, *, amount_kopecks: int, received_on: date, method: PaymentMethod,
                   document_ref: str, note: str = "", confirmed_by: uuid.UUID | None, source: str = "staff",
                   external_ref: str = "", report_id: uuid.UUID | None = None,
                   corrects_payment_id: uuid.UUID | None = None) -> Payment:
    if c.status not in LIVE:
        raise HTTPException(409, "Платёж можно учесть только по подписанному договору")
    if received_on > today():
        raise HTTPException(422, "Дата поступления не может быть в будущем")
    if received_on < c.contract_date:
        raise HTTPException(422, "Дата поступления раньше даты договора")
    outstanding = ledger_for(db, c).outstanding_kopecks
    if amount_kopecks > outstanding:
        raise HTTPException(422, f"Сумма больше остатка долга ({rub(outstanding)}). Переплату оформите отдельно.")
    if method == PaymentMethod.bank_transfer and db.scalar(select(Payment.id).where(
            Payment.contract_id == c.id, Payment.status == PaymentStatus.confirmed,
            Payment.document_ref == document_ref, Payment.method == method)):
        raise HTTPException(409, "Платёж с таким номером документа уже учтён")
    if external_ref and db.scalar(select(Payment.id).where(Payment.external_ref == external_ref,
                                                           Payment.status == PaymentStatus.confirmed)):
        raise HTTPException(409, "Это поступление уже учтено")
    report = None
    if report_id:
        report = db.get(PaymentReport, report_id)
        if not report or report.contract_id != c.id or report.status != PaymentReportStatus.pending:
            raise HTTPException(409, "Сообщение об оплате не найдено или уже обработано")
    if corrects_payment_id:
        original = db.get(Payment, corrects_payment_id)
        if not original or original.contract_id != c.id or original.status != PaymentStatus.reversed:
            raise HTTPException(409, "Исправлять можно только сторнированный платёж этого договора")

    p = Payment(contract_id=c.id, amount_kopecks=amount_kopecks, received_on=received_on, method=method,
                document_ref=document_ref, note=note, confirmed_by=confirmed_by, source=source,
                external_ref=external_ref, report_id=report_id, corrects_payment_id=corrects_payment_id)
    db.add(p)
    if report:
        report.status = PaymentReportStatus.matched
        report.reviewed_by = confirmed_by
        report.reviewed_at = datetime.now(UTC)
        report.review_note = "Платёж найден и учтён"
    db.flush()
    sync_completion(db, c)
    # Подтверждение оплаты: в кабинет сразу, во внешние каналы — через журнал и очередь с проверками
    dispatch_payment_confirmed(db, c, p, datetime.now(UTC))
    if c.status == ContractStatus.completed:
        notify_client(db, c.client_id, "contract.completed", f"Договор № {c.number} полностью оплачен",
                      "Обязательства по оплате исполнены.", f"/cabinet/contracts/{c.id}")
    return p
