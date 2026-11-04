"""Онлайн-оплата через платёжный сервис.

Платёж по договору учитывается только после того, как сервер сам запросил статус у провайдера и получил
«оплачено» на ту же сумму. Уведомлению провайдера (webhook) и возврату покупателя на сайт не доверяем —
это только повод перепроверить статус.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Contract, ContractStatus, Payment, PaymentIntent, PaymentMethod, PaymentStatus
from app.services import audit
from app.services.common import today
from app.services.contracts import ledger_for
from app.services.http import HttpError, request_json
from app.services.notify import notify_staff, rub
from app.services.payments import record_payment
from app.services.staff_tasks import open_task

MAX_INTENTS_PER_HOUR = 10
SYNC_DAYS = 3
OPEN = ("pending", "needs_review")


class PaymentProviderError(Exception):
    pass


@dataclass
class ProviderPayment:
    id: str
    status: str  # pending | succeeded | canceled
    amount_kopecks: int
    confirmation_url: str = ""
    paid_at: datetime | None = None
    currency: str = "RUB"
    test: bool = False


class SandboxProvider:
    """Тестовая оплата для разработки: деньги не списываются. В production не подключается."""

    name = "sandbox"
    test_mode = True

    @staticmethod
    def path(payment_id: str):
        d = get_settings().storage_dir / "sandbox-payments"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{payment_id}.json"

    def create(self, intent: PaymentIntent, description: str, return_url: str) -> ProviderPayment:
        pp = ProviderPayment(id=f"sbx_{uuid.uuid4().hex}", status="pending", amount_kopecks=intent.amount_kopecks,
                             confirmation_url=f"/cabinet/payments/{intent.id}")
        self.path(pp.id).write_text(json.dumps({"status": "pending", "amount": pp.amount_kopecks}), encoding="utf-8")
        return pp

    def fetch(self, payment_id: str) -> ProviderPayment:
        p = self.path(payment_id)
        if not p.exists():
            raise PaymentProviderError("Тестовый платёж не найден")
        data = json.loads(p.read_text(encoding="utf-8"))
        paid_at = datetime.fromisoformat(data["paid_at"]) if data.get("paid_at") else None
        return ProviderPayment(id=payment_id, status=data["status"], amount_kopecks=data["amount"], paid_at=paid_at)

    def simulate(self, payment_id: str, result: str) -> None:
        current = self.fetch(payment_id)
        if current.status != "pending":
            raise PaymentProviderError("Тестовый платёж уже завершён")
        data = {"status": result, "amount": current.amount_kopecks}
        if result == "succeeded":
            data["paid_at"] = datetime.now(UTC).isoformat()
        self.path(payment_id).write_text(json.dumps(data), encoding="utf-8")


class YooKassaProvider:
    """ЮKassa (API v3). Реализовано по документации https://yookassa.ru/developers, на реальном магазине не проверялось.

    Чек по 54-ФЗ в запрос не добавляется: способ формирования чеков определяет бухгалтер.
    """

    name = "yookassa"

    def __init__(self) -> None:
        s = get_settings()
        self.base = s.yookassa_api_url.rstrip("/")
        self.auth = (s.yookassa_shop_id, s.yookassa_secret_key)
        self.test_mode = s.yookassa_secret_key.startswith("test_")

    @staticmethod
    def to_payment(data: dict) -> ProviderPayment:
        status = {"succeeded": "succeeded", "canceled": "canceled"}.get(data.get("status", ""), "pending")
        value = (data.get("amount") or {}).get("value", "0")
        amount = int(Decimal(str(value)) * 100)
        paid_at = data.get("captured_at") if status == "succeeded" else None
        return ProviderPayment(id=data["id"], status=status, amount_kopecks=amount,
                               confirmation_url=(data.get("confirmation") or {}).get("confirmation_url", ""),
                               currency=(data.get("amount") or {}).get("currency", ""),
                               test=data.get("test") is not False,
                               paid_at=datetime.fromisoformat(paid_at.replace("Z", "+00:00")) if paid_at else None)

    def create(self, intent: PaymentIntent, description: str, return_url: str) -> ProviderPayment:
        body = {
            "amount": {"value": f"{intent.amount_kopecks // 100}.{intent.amount_kopecks % 100:02d}", "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description[:128],
            "metadata": {"intent_id": str(intent.id)},
        }
        try:
            data = request_json("POST", f"{self.base}/payments", json_body=body, basic_auth=self.auth,
                                headers={"Idempotence-Key": intent.idempotence_key})
        except HttpError as e:
            raise PaymentProviderError(f"ЮKassa: {e} {e.body if isinstance(e.body, dict) else ''}".strip()) from e
        return self.to_payment(data)

    def fetch(self, payment_id: str) -> ProviderPayment:
        try:
            return self.to_payment(request_json("GET", f"{self.base}/payments/{payment_id}", basic_auth=self.auth))
        except HttpError as e:
            raise PaymentProviderError(f"ЮKassa: {e}") from e


def get_payment_provider():
    """Подключённый провайдер или None — тогда кнопки онлайн-оплаты нет."""
    s = get_settings()
    if s.payment_provider == "sandbox" and not s.is_production:
        return SandboxProvider()
    if s.payment_provider == "yookassa" and s.yookassa_shop_id and s.yookassa_secret_key:
        if s.is_production and (not s.payment_receipts_confirmed or s.yookassa_secret_key.startswith("test_")):
            return None
        return YooKassaProvider()
    return None


def provider_for(name: str):
    p = get_payment_provider()
    return p if p and p.name == name else None


def online_status() -> dict:
    p = get_payment_provider()
    return {"enabled": p is not None, "provider": p.name if p else "", "test_mode": bool(p and p.test_mode)}


def create_intent(db: Session, c: Contract, amount_kopecks: int) -> PaymentIntent:
    provider = get_payment_provider()
    if provider is None:
        raise HTTPException(409, "Онлайн-оплата не подключена. Оплатите по реквизитам.")
    if c.status != ContractStatus.signed:
        raise HTTPException(409, "Договор уже полностью оплачен")
    outstanding = ledger_for(db, c).outstanding_kopecks
    if amount_kopecks > outstanding:
        raise HTTPException(422, f"Сумма больше остатка ({rub(outstanding)})")
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    recent = db.scalar(select(func.count(PaymentIntent.id)).where(PaymentIntent.client_id == c.client_id,
                                                                  PaymentIntent.created_at >= hour_ago))
    if recent >= MAX_INTENTS_PER_HOUR:
        raise HTTPException(429, "Слишком много попыток оплаты. Попробуйте позже.")
    intent = PaymentIntent(contract_id=c.id, client_id=c.client_id, amount_kopecks=amount_kopecks,
                           provider=provider.name, idempotence_key=uuid.uuid4().hex)
    db.add(intent)
    db.flush()
    return_url = f"{get_settings().client_public_url.rstrip('/')}/cabinet/payments/{intent.id}"
    try:
        pp = provider.create(intent, f"Оплата по договору № {c.number}", return_url)
    except PaymentProviderError as e:
        intent.status, intent.error = "failed", str(e)[:2000]
        return intent
    intent.provider_payment_id, intent.confirmation_url, intent.status = pp.id, pp.confirmation_url, "pending"
    return intent


def needs_review(db: Session, intent: PaymentIntent, c: Contract, reason: str) -> None:
    """Деньги у провайдера получены, но автоматически учесть нельзя — разбирает сотрудник."""
    intent.status, intent.error = "needs_review", reason[:2000]
    title = f"Онлайн-оплата по договору № {c.number} требует проверки"
    body = f"{rub(intent.amount_kopecks)}, платёж провайдера {intent.provider_payment_id}. {reason}"
    notify_staff(db, "payment.online_review", title, body, "/payments")
    open_task(db, "payment_online_review", title, body, "/payments", dedupe_key=f"intent-review:{intent.id}")


def sync_intent(db: Session, intent_id: uuid.UUID) -> PaymentIntent:
    """Запрашивает статус у провайдера и, если оплата подтверждена, учитывает платёж. Повторный вызов безопасен."""
    intent = db.scalar(select(PaymentIntent).where(PaymentIntent.id == intent_id).with_for_update()
                       .execution_options(populate_existing=True))
    if intent is None or intent.status not in OPEN or intent.payment_id or not intent.provider_payment_id:
        return intent
    provider = provider_for(intent.provider)
    if provider is None:
        intent.error = "Платёжный сервис сейчас не подключён — статус проверить нельзя"
        return intent
    try:
        pp = provider.fetch(intent.provider_payment_id)
    except PaymentProviderError as e:
        intent.error = str(e)[:2000]
        return intent
    intent.error = ""
    c = db.get(Contract, intent.contract_id)
    if (pp.id != intent.provider_payment_id or pp.currency != "RUB"
            or (get_settings().is_production and pp.test)):
        needs_review(db, intent, c, "Не совпадает идентификатор, валюта или рабочий режим платежа")
        return intent
    if pp.status == "canceled":
        intent.status = "canceled"
        return intent
    if pp.status != "succeeded":
        return intent
    if pp.amount_kopecks != intent.amount_kopecks:
        needs_review(db, intent, c, f"Сумма у провайдера ({rub(pp.amount_kopecks)}) отличается от заказанной")
        return intent
    external_ref = f"{provider.name}:{pp.id}"
    existing = db.scalar(select(Payment).where(Payment.external_ref == external_ref,
                                               Payment.status == PaymentStatus.confirmed))
    if existing and existing.contract_id != c.id:
        needs_review(db, intent, c, "Платёж уже относится к другому договору")
        return intent
    if existing:
        intent.status, intent.payment_id = "succeeded", existing.id
        return intent
    tz = ZoneInfo(get_settings().company_timezone)
    received_on = min(pp.paid_at.astimezone(tz).date(), today()) if pp.paid_at else today()
    try:
        p = record_payment(db, c, amount_kopecks=pp.amount_kopecks, received_on=received_on,
                           method=PaymentMethod.online, document_ref=f"{provider.name} {pp.id}"[:120],
                           note="Онлайн-оплата: статус «оплачено» получен сервером у платёжного сервиса",
                           confirmed_by=None, source="provider", external_ref=external_ref)
    except HTTPException as e:
        needs_review(db, intent, c, str(e.detail))
        return intent
    intent.status, intent.payment_id = "succeeded", p.id
    audit.record(db, None, "payment.online_confirmed", "payment", p.id, contract=c.number, amount=p.amount_kopecks,
                 provider=provider.name, provider_payment_id=pp.id)
    return intent


def sync_pending(db: Session, now: datetime) -> int:
    """Фоновая перепроверка незавершённых оплат: на случай, если уведомление провайдера не дошло."""
    since = now - timedelta(days=SYNC_DAYS)
    ids = list(db.scalars(select(PaymentIntent.id).where(PaymentIntent.status == "pending")))
    for intent_id in ids:
        intent = sync_intent(db, intent_id)
        created = intent.created_at if intent.created_at.tzinfo else intent.created_at.replace(tzinfo=UTC)
        # Последняя проверка выполнена: незавершённая за 3 дня оплата закрывается
        if intent.status == "pending" and not intent.error and created < since:
            intent.status, intent.error = "expired", f"Оплата не завершена за {SYNC_DAYS} дня"
        db.commit()
    return len(ids)
