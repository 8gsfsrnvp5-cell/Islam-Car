"""Онлайн-оплата: кабинет покупателя, уведомления платёжного сервиса, журнал для сотрудников."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Contract, PaymentIntent
from app.routers.client import own_contract
from app.schemas import StrictModel
from app.security import Actor, current_client, require
from app.services import audit
from app.services.online_payments import (
    OPEN,
    PaymentProviderError,
    SandboxProvider,
    create_intent,
    online_status,
    provider_for,
    sync_intent,
)

router = APIRouter(prefix="/api/payments", tags=["payments: webhooks"])
client_router = APIRouter(prefix="/api/client", tags=["client"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin: contracts"])

MAX_WEBHOOK_BYTES = 64 * 1024


class OnlinePaymentIn(StrictModel):
    amount_kopecks: int = Field(gt=0, le=10**13)


class SandboxResultIn(StrictModel):
    result: Literal["succeeded", "canceled"]


def intent_client(i: PaymentIntent, number: str | None) -> dict[str, Any]:
    return {"id": i.id, "contract_id": i.contract_id, "contract_number": number, "amount_kopecks": i.amount_kopecks,
            "provider": i.provider, "test_mode": i.provider == "sandbox", "status": i.status,
            "confirmation_url": i.confirmation_url if i.status == "pending" else "", "created_at": i.created_at}


def intent_staff(i: PaymentIntent, number: str | None) -> dict[str, Any]:
    return {**intent_client(i, number), "provider_payment_id": i.provider_payment_id, "payment_id": i.payment_id,
            "error": i.error, "updated_at": i.updated_at}


def own_intent(db: Session, actor: Actor, intent_id: uuid.UUID) -> PaymentIntent:
    i = db.get(PaymentIntent, intent_id)
    if not i or i.client_id != actor.user.client_id:
        raise HTTPException(404, "Оплата не найдена")
    return i


def number_of(db: Session, contract_id: uuid.UUID) -> str | None:
    return db.scalar(select(Contract.number).where(Contract.id == contract_id))


# ---- Кабинет покупателя ----

@client_router.get("/online-payment")
def client_online_status(actor: Actor = Depends(current_client)):
    return online_status()


@client_router.post("/contracts/{contract_id}/online-payments", status_code=201)
def start_online_payment(contract_id: uuid.UUID, data: OnlinePaymentIn, actor: Actor = Depends(current_client),
                         db: Session = Depends(get_db)):
    """Создаёт оплату у провайдера и возвращает адрес страницы оплаты. Сам платёж здесь не учитывается."""
    c = own_contract(db, actor, contract_id)
    intent = create_intent(db, c, data.amount_kopecks)
    db.commit()
    if intent.status == "failed":
        raise HTTPException(502, "Платёжный сервис недоступен. Попробуйте позже или оплатите по реквизитам.")
    return intent_client(intent, c.number)


@client_router.get("/online-payments/{intent_id}")
def online_payment_status(intent_id: uuid.UUID, actor: Actor = Depends(current_client),
                          db: Session = Depends(get_db)):
    """Статус после возврата со страницы оплаты: сервер сам перепроверяет его у провайдера."""
    intent = own_intent(db, actor, intent_id)
    if intent.status == "pending":
        intent = sync_intent(db, intent.id)
        db.commit()
    return intent_client(intent, number_of(db, intent.contract_id))


@client_router.post("/online-payments/{intent_id}/sandbox")
def sandbox_result(intent_id: uuid.UUID, data: SandboxResultIn, actor: Actor = Depends(current_client),
                   db: Session = Depends(get_db)):
    """Только для тестового провайдера в разработке: имитирует результат на «стороне банка»."""
    intent = own_intent(db, actor, intent_id)
    provider = provider_for(intent.provider)
    if not isinstance(provider, SandboxProvider):
        raise HTTPException(404, "Оплата не найдена")
    try:
        provider.simulate(intent.provider_payment_id, data.result)
    except PaymentProviderError as e:
        raise HTTPException(409, str(e)) from None
    intent = sync_intent(db, intent.id)
    db.commit()
    return intent_client(intent, number_of(db, intent.contract_id))


# ---- Уведомления платёжного сервиса ----

@router.post("/webhook/{provider}")
async def provider_webhook(provider: str, request: Request, db: Session = Depends(get_db)):
    """Уведомлению не доверяем: по идентификатору находим свою оплату и перепроверяем статус у провайдера."""
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, "Слишком большое уведомление")
    try:
        payload = await request.json()
        payment_id = str((payload.get("object") or {}).get("id") or "")
    except (ValueError, AttributeError):
        raise HTTPException(400, "Некорректное уведомление") from None
    intent = db.scalar(select(PaymentIntent).where(PaymentIntent.provider == provider,
                                                   PaymentIntent.provider_payment_id == payment_id)) \
        if payment_id else None
    if intent and intent.status in OPEN:
        sync_intent(db, intent.id)
        db.commit()
    return {"ok": True}  # неизвестные уведомления подтверждаем, чтобы сервис не повторял их бесконечно


# ---- Сотрудники ----

@admin_router.get("/payment-intents")
def list_intents(status: str | None = None, actor: Actor = Depends(require("payments.read")),
                 db: Session = Depends(get_db)):
    stmt = select(PaymentIntent, Contract.number).join(Contract, Contract.id == PaymentIntent.contract_id) \
        .order_by(PaymentIntent.created_at.desc()).limit(500)
    if status:
        stmt = stmt.where(PaymentIntent.status == status)
    return [intent_staff(i, n) for i, n in db.execute(stmt)]


@admin_router.post("/payment-intents/{intent_id}/sync")
def resync_intent(intent_id: uuid.UUID, actor: Actor = Depends(require("payments.confirm")),
                  db: Session = Depends(get_db)):
    """Повторная проверка у провайдера — например, после того как сотрудник разобрал причину задержки."""
    intent = db.get(PaymentIntent, intent_id)
    if not intent:
        raise HTTPException(404, "Оплата не найдена")
    if intent.status not in OPEN:
        raise HTTPException(409, "Оплата уже завершена")
    intent = sync_intent(db, intent.id)
    audit.record(db, actor, "payment_intent.resynced", "payment_intent", intent.id, status=intent.status)
    db.commit()
    return intent_staff(intent, number_of(db, intent.contract_id))
