"""Банковские выписки: загрузка, предложенные совпадения, подтверждение поступлений сотрудником."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import BankImport, BankTransaction, Contract, PaymentMethod
from app.routers.admin_contracts import get_contract
from app.schemas import BankConfirmIn, ReverseIn
from app.security import Actor, require
from app.serializers import payment_dict
from app.services import audit
from app.services.bank_import import StatementError, import_statement
from app.services.contracts import ledger_for
from app.services.payments import record_payment

router = APIRouter(prefix="/api/admin/bank", tags=["admin: bank"])

STATUSES = {"new", "suggested", "confirmed", "ignored"}


def import_dict(i: BankImport) -> dict[str, Any]:
    return {"id": i.id, "file_name": i.file_name, "file_format": i.file_format, "account": i.account,
            "period_from": i.period_from, "period_to": i.period_to, "rows_total": i.rows_total,
            "rows_incoming": i.rows_incoming, "rows_new": i.rows_new, "created_at": i.created_at}


def mask_account(account: str) -> str:
    return f"…{account[-4:]}" if account else ""


def tx_dict(tx: BankTransaction, numbers: dict[uuid.UUID, str | None], actor: Actor) -> dict[str, Any]:
    pd = actor.can("clients.pd")
    return {
        "id": tx.id, "import_id": tx.import_id, "doc_number": tx.doc_number, "doc_date": tx.doc_date,
        "received_on": tx.received_on, "amount_kopecks": tx.amount_kopecks,
        "payer_name": tx.payer_name if pd or actor.can("payments.confirm") else "скрыто",
        "payer_inn": tx.payer_inn if pd else ("скрыт" if tx.payer_inn else ""),
        "payer_account": tx.payer_account if pd else mask_account(tx.payer_account),
        "purpose": tx.purpose, "status": tx.status, "match_contract_id": tx.match_contract_id,
        "match_contract_number": numbers.get(tx.match_contract_id) if tx.match_contract_id else None,
        "match_score": tx.match_score, "match_reasons": tx.match_reasons, "payment_id": tx.payment_id,
        "note": tx.note, "reviewed_at": tx.reviewed_at,
    }


def contract_numbers(db: Session, txs: list[BankTransaction]) -> dict[uuid.UUID, str | None]:
    ids = {t.match_contract_id for t in txs if t.match_contract_id}
    if not ids:
        return {}
    return {cid: num for cid, num in db.execute(select(Contract.id, Contract.number).where(Contract.id.in_(ids)))}


def get_tx(db: Session, tx_id: uuid.UUID) -> BankTransaction:
    tx = db.scalar(select(BankTransaction).where(BankTransaction.id == tx_id).with_for_update()
                   .execution_options(populate_existing=True))
    if not tx:
        raise HTTPException(404, "Поступление не найдено")
    return tx


@router.post("/imports", status_code=201)
async def upload_statement(file: UploadFile = File(...), actor: Actor = Depends(require("payments.import")),
                           db: Session = Depends(get_db)):
    """Загружает выписку 1C. Создаются только записи о поступлениях — платежи по договорам подтверждает сотрудник."""
    limit = get_settings().max_document_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, "Файл слишком большой")
    try:
        imp = import_statement(db, content, file.filename or "выписка.txt", actor.user.id)
    except StatementError as e:
        db.rollback()
        raise HTTPException(409 if "уже загружена" in str(e) else 422, str(e)) from None
    audit.record(db, actor, "bank.statement_imported", "bank_import", imp.id, file_sha256=imp.file_sha256,
                 rows_incoming=imp.rows_incoming, rows_new=imp.rows_new)
    db.commit()
    return import_dict(imp)


@router.get("/imports")
def list_imports(actor: Actor = Depends(require("payments.read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(BankImport).order_by(BankImport.created_at.desc()).limit(200))
    return [import_dict(i) for i in rows]


@router.get("/transactions")
def list_transactions(status: str | None = None, import_id: uuid.UUID | None = None,
                      actor: Actor = Depends(require("payments.read")), db: Session = Depends(get_db)):
    stmt = select(BankTransaction).order_by(BankTransaction.received_on.desc(), BankTransaction.doc_number).limit(1000)
    if status:
        if status not in STATUSES and status != "open":
            raise HTTPException(422, "Неизвестный статус")
        stmt = stmt.where(BankTransaction.status.in_(("new", "suggested")) if status == "open"
                          else BankTransaction.status == status)
    if import_id:
        stmt = stmt.where(BankTransaction.import_id == import_id)
    txs = list(db.scalars(stmt))
    numbers = contract_numbers(db, txs)
    return [tx_dict(t, numbers, actor) for t in txs]


@router.post("/transactions/{tx_id}/confirm")
def confirm_transaction(tx_id: uuid.UUID, data: BankConfirmIn, actor: Actor = Depends(require("payments.confirm")),
                        db: Session = Depends(get_db)):
    """Сотрудник подтверждает, что поступление — оплата по выбранному договору. Только тогда учитывается платёж."""
    tx = get_tx(db, tx_id)
    if tx.status not in ("new", "suggested"):
        raise HTTPException(409, "Поступление уже обработано")
    c = get_contract(db, data.contract_id)
    p = record_payment(db, c, amount_kopecks=tx.amount_kopecks, received_on=tx.received_on,
                       method=PaymentMethod.bank_transfer,
                       document_ref=f"п/п № {tx.doc_number} от {tx.doc_date:%d.%m.%Y}"[:120],
                       note=data.note, confirmed_by=actor.user.id, source="bank_statement",
                       external_ref=tx.external_key, report_id=data.report_id)
    suggested = tx.match_contract_id
    tx.status, tx.payment_id, tx.match_contract_id = "confirmed", p.id, c.id
    tx.note, tx.reviewed_by, tx.reviewed_at = data.note, actor.user.id, datetime.now(UTC)
    audit.record(db, actor, "bank.transaction_confirmed", "bank_transaction", tx.id, contract=c.number,
                 amount=tx.amount_kopecks, payment_id=str(p.id), as_suggested=suggested == c.id)
    db.commit()
    return {"transaction": tx_dict(tx, {c.id: c.number}, actor), "payment": payment_dict(p),
            "ledger_outstanding_kopecks": ledger_for(db, c).outstanding_kopecks, "contract_status": c.status}


@router.post("/transactions/{tx_id}/ignore")
def ignore_transaction(tx_id: uuid.UUID, data: ReverseIn, actor: Actor = Depends(require("payments.confirm")),
                       db: Session = Depends(get_db)):
    """Поступление не относится к договорам (например, возврат поставщика). Запись сохраняется."""
    tx = get_tx(db, tx_id)
    if tx.status not in ("new", "suggested"):
        raise HTTPException(409, "Поступление уже обработано")
    tx.status, tx.note, tx.reviewed_by, tx.reviewed_at = "ignored", data.reason, actor.user.id, datetime.now(UTC)
    audit.record(db, actor, "bank.transaction_ignored", "bank_transaction", tx.id, reason=data.reason)
    db.commit()
    return tx_dict(tx, contract_numbers(db, [tx]), actor)


@router.post("/transactions/{tx_id}/reopen")
def reopen_transaction(tx_id: uuid.UUID, actor: Actor = Depends(require("payments.confirm")),
                       db: Session = Depends(get_db)):
    tx = get_tx(db, tx_id)
    if tx.status != "ignored":
        raise HTTPException(409, "Вернуть в работу можно только отложенное поступление")
    tx.status, tx.reviewed_by, tx.reviewed_at = "new", None, None
    audit.record(db, actor, "bank.transaction_reopened", "bank_transaction", tx.id)
    db.commit()
    return tx_dict(tx, contract_numbers(db, [tx]), actor)
