"""Сообщения клиентам: тексты, согласия, допустимое время и частота, журнал, отправка.

Каждое сообщение — запись в outbound_messages с уникальным event_key (защита от повторов).
Перед отправкой состояние долга проверяется заново: оплаченный платёж не вызывает напоминания.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Audience,
    Channel,
    Client,
    Consent,
    ConsentPurpose,
    Contract,
    ContractStatus,
    MessageStatus,
    Notification,
    NotificationEvent,
    NotificationRule,
    OutboundMessage,
    PartyType,
    Payment,
    PaymentStatus,
)
from app.services.common import mask_phone, mask_tail
from app.services.contracts import get_company, ledger_for
from app.services.notify import notify_staff
from app.services.providers import ProviderError, get_provider

# Значения по умолчанию взяты из ст. 7 Федерального закона № 230-ФЗ и требуют проверки юристом.
# Время применяется ко всем внешним сообщениям, частота — к сообщениям о просрочке.
DEFAULT_POLICY: dict = {
    "weekday_from": "08:00", "weekday_to": "22:00",
    "weekend_from": "09:00", "weekend_to": "20:00",
    "overdue_per_day": 2, "overdue_per_week": 4, "overdue_per_month": 16,
    "holidays": [],
    "basis": "ст. 7 Федерального закона от 03.07.2016 № 230-ФЗ — параметры требуют проверки юристом",
}

DEFAULT_RULES = [("before_due", 5), ("before_due", 1), ("due_day", 0), ("overdue", 1), ("overdue", 7),
                 ("payment_confirmed", 0)]
MAX_SEND_ATTEMPTS = 3
EXTERNAL = (Channel.sms, Channel.email)
LIMITED_PARTIES = (PartyType.individual, PartyType.ip)  # долги граждан — режим 230-ФЗ

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]


# --- Тексты -------------------------------------------------------------------

def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def rub_words(kopecks: int) -> str:
    """50 000 рублей; 1 рубль 50 копеек — как в примерах из ТЗ."""
    rubles, kop = divmod(kopecks, 100)
    text = f"{rubles:,}".replace(",", " ") + " " + plural(rubles, "рубль", "рубля", "рублей")
    if kop:
        text += f" {kop:02d} " + plural(kop, "копейка", "копейки", "копеек")
    return text


def day_month(d: date) -> str:
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def render(purpose: NotificationEvent, number: str, ctx: dict) -> tuple[str, str]:
    """Возвращает (тема письма, текст). Тексты нейтральные, без угроз и давления."""
    amount = rub_words(ctx["amount_kopecks"])
    if purpose == NotificationEvent.payment_confirmed:
        return (f"Платёж {amount} по договору № {number} получен и учтён",
                f"Islamic Car. Платёж {amount} по договору № {number} получен и учтён. "
                f"Благодарим за своевременную оплату.")
    due = date.fromisoformat(ctx["due_date"])
    if purpose == NotificationEvent.before_due:
        return (f"Напоминание о платеже по договору № {number}",
                f"Islamic Car. Напоминаем, что {day_month(due)} по договору № {number} ожидается платёж {amount}. "
                f"Информация доступна в вашем личном кабинете.")
    if purpose == NotificationEvent.due_day:
        return (f"Срок платежа по договору № {number} — сегодня",
                f"Islamic Car. Сегодня, {day_month(due)}, по договору № {number} ожидается платёж {amount}. "
                f"Информация доступна в вашем личном кабинете.")
    return (f"Платёж по договору № {number} не поступил",
            f"Islamic Car. По договору № {number} не поступил платёж {amount}, срок оплаты — {day_month(due)}. "
            f"Проценты и штрафы не начисляются. Если вы уже оплатили, сообщите об этом в личном кабинете. "
            f"Если возникли трудности, напишите нам — обсудим решение.")


# --- Правила и политика -----------------------------------------------------------

def ensure_default_rules(db: Session) -> list[NotificationRule]:
    rules = list(db.scalars(select(NotificationRule)))
    if not rules:
        for event, days in DEFAULT_RULES:
            db.add(NotificationRule(event=event, offset_days=days, channels=["internal", "sms", "email"]))
        db.flush()
        rules = list(db.scalars(select(NotificationRule)))
    return rules


def get_policy(db: Session) -> dict:
    return {**DEFAULT_POLICY, **(get_company(db).communication_policy or {})}


def _hm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def next_allowed_time(policy: dict, tz_name: str, at: datetime) -> datetime:
    """Ближайший момент не раньше `at`, когда разрешено писать клиенту по его местному времени."""
    tz = ZoneInfo(tz_name or "Europe/Moscow")
    local = at.astimezone(tz)
    holidays = set(policy.get("holidays") or [])
    for day_offset in range(0, 15):
        day = local.date() + timedelta(days=day_offset)
        weekend = day.weekday() >= 5 or day.isoformat() in holidays
        start = _hm(policy["weekend_from" if weekend else "weekday_from"])
        end = _hm(policy["weekend_to" if weekend else "weekday_to"])
        window_start = datetime.combine(day, start, tz)
        window_end = datetime.combine(day, end, tz)
        candidate = max(window_start, local) if day_offset == 0 else window_start
        if candidate < window_end:
            return candidate.astimezone(UTC)
    return at


def frequency_wait_until(db: Session, client_id: uuid.UUID, policy: dict, now: datetime) -> datetime:
    """Когда можно отправить следующее сообщение о просрочке без превышения лимитов частоты."""
    sent = sorted(db.scalars(select(OutboundMessage.sent_at).where(
        OutboundMessage.client_id == client_id, OutboundMessage.purpose == NotificationEvent.overdue,
        OutboundMessage.channel.in_(EXTERNAL), OutboundMessage.status == MessageStatus.sent,
        OutboundMessage.sent_at >= now - timedelta(days=30))))
    sent = [s if s.tzinfo else s.replace(tzinfo=UTC) for s in sent]
    wait = now
    for days, key in ((1, "overdue_per_day"), (7, "overdue_per_week"), (30, "overdue_per_month")):
        limit = int(policy[key])
        window = [s for s in sent if s >= now - timedelta(days=days)]
        if limit > 0 and len(window) >= limit:
            wait = max(wait, window[-limit] + timedelta(days=days))
    return wait


# --- Согласия и контакты ---------------------------------------------------------

def current_consents(db: Session, client_id: uuid.UUID) -> dict[str, dict]:
    """Последняя запись по каждому каналу (сервисные сообщения)."""
    rows = db.scalars(select(Consent).where(Consent.client_id == client_id,
                                            Consent.purpose == ConsentPurpose.service)
                      .order_by(Consent.recorded_at)).all()
    result: dict[str, dict] = {}
    for r in rows:
        result[r.channel.value] = {"granted": r.granted, "source": r.source, "recorded_at": r.recorded_at}
    return result


def has_consent(db: Session, client_id: uuid.UUID, channel: Channel) -> bool:
    return bool(current_consents(db, client_id).get(channel.value, {}).get("granted"))


def address_for(client: Client, channel: Channel) -> tuple[str | None, str]:
    """(адрес, маскированный адрес). None — контакт не подтверждён."""
    if channel == Channel.sms:
        return (client.phone, mask_phone(client.phone)) if client.phone_verified and client.phone else (None, "")
    if channel == Channel.email:
        if client.email_verified and client.email:
            name, _, domain = client.email.partition("@")
            return client.email, f"{mask_tail(name, 2)}@{domain}"
        return None, ""
    return None, ""


# --- Создание сообщений ------------------------------------------------------------

def _deliver_internal(db: Session, msg: OutboundMessage, subject: str, link: str, now: datetime) -> None:
    db.add(Notification(audience=Audience.client, client_id=msg.client_id, kind=f"message.{msg.purpose.value}",
                        title=subject, body=msg.body, link=link))
    msg.status = MessageStatus.sent
    msg.sent_at = now
    msg.provider = "cabinet"


def create_messages(db: Session, contract: Contract, purpose: NotificationEvent, key: str, ctx: dict,
                    channels: list[str], now: datetime) -> list[OutboundMessage]:
    """Ставит сообщения в очередь. Уже созданные по тому же ключу пропускаются."""
    from app.worker.queue import enqueue  # локальный импорт: очередь зависит от моделей, а не наоборот

    created = []
    subject, body = render(purpose, contract.number or "", ctx)
    link = f"/cabinet/contracts/{contract.id}"
    for ch_name in channels:
        channel = Channel(ch_name)
        event_key = f"{purpose.value}:{contract.id}:{key}:{channel.value}"
        if db.scalar(select(OutboundMessage.id).where(OutboundMessage.event_key == event_key)):
            continue
        msg = OutboundMessage(client_id=contract.client_id, contract_id=contract.id, channel=channel, purpose=purpose,
                              event_key=event_key, context=ctx, body=body, scheduled_for=now)
        try:
            with db.begin_nested():
                db.add(msg)
                db.flush()
        except IntegrityError:
            continue  # параллельный планировщик уже создал это сообщение
        if channel == Channel.internal:
            reason = relevance_problem(db, msg, contract, now)
            if reason:
                msg.status = MessageStatus.cancelled
                msg.status_reason = reason
            else:
                _deliver_internal(db, msg, subject, link, now)
        else:
            enqueue(db, "send_message", {"message_id": str(msg.id)}, run_at=now, dedupe_key=f"send:{msg.id}:0")
        created.append(msg)
    return created


def dispatch_payment_confirmed(db: Session, contract: Contract, payment: Payment, now: datetime) -> None:
    rule = next((r for r in ensure_default_rules(db)
                 if r.event == NotificationEvent.payment_confirmed and r.enabled), None)
    if rule is None:
        return
    ctx = {"payment_id": str(payment.id), "amount_kopecks": payment.amount_kopecks,
           "received_on": payment.received_on.isoformat()}
    create_messages(db, contract, NotificationEvent.payment_confirmed, str(payment.id), ctx, rule.channels, now)


# --- Проверка перед отправкой и отправка ------------------------------------------------

def _local_date(now: datetime) -> date:
    from app.config import get_settings
    return now.astimezone(ZoneInfo(get_settings().company_timezone)).date()


def relevance_problem(db: Session, msg: OutboundMessage, contract: Contract, now: datetime) -> str | None:
    """Причина отменить сообщение или None. Вызывается непосредственно перед отправкой."""
    ctx = msg.context
    if msg.purpose == NotificationEvent.payment_confirmed:
        payment = db.get(Payment, uuid.UUID(ctx["payment_id"]))
        if not payment or payment.status != PaymentStatus.confirmed:
            return "Платёж сторнирован — подтверждение не отправляется"
        return None
    if contract.status != ContractStatus.signed:
        return "Договор не действует или полностью оплачен"
    if ctx.get("schedule_version", 1) != contract.schedule_version:
        return "График изменён дополнительным соглашением"
    ledger = ledger_for(db, contract, _local_date(now))
    row = next((r for r in ledger.rows if r.seq == ctx["seq"]), None)
    if row is None or row.remaining_kopecks == 0:
        return "Платёж уже поступил — сообщение отменено"
    if msg.purpose == NotificationEvent.overdue and row.status != "overdue":
        return "Просрочки нет — сообщение отменено"
    amount = ledger.overdue_kopecks if msg.purpose == NotificationEvent.overdue else row.remaining_kopecks
    ctx = {**ctx, "amount_kopecks": amount}
    msg.context = ctx
    msg.body = render(msg.purpose, contract.number or "", ctx)[1]
    return None


def send_message(db: Session, message_id: uuid.UUID, now: datetime) -> None:
    from app.worker.queue import enqueue

    msg = db.get(OutboundMessage, message_id)
    if not msg or msg.status != MessageStatus.scheduled:
        return
    contract = db.get(Contract, msg.contract_id) if msg.contract_id else None
    client = db.get(Client, msg.client_id)

    def finish(status: MessageStatus, reason: str) -> None:
        msg.status = status
        msg.status_reason = reason

    if contract is None:
        return finish(MessageStatus.cancelled, "Договор не найден")
    reason = relevance_problem(db, msg, contract, now)
    if reason:
        return finish(MessageStatus.cancelled, reason)
    provider = get_provider(msg.channel)
    if provider is None:
        return finish(MessageStatus.skipped, "Канал не подключён")
    if not has_consent(db, client.id, msg.channel):
        return finish(MessageStatus.skipped, "Нет согласия клиента на сообщения по этому каналу")
    address, masked = address_for(client, msg.channel)
    if not address:
        return finish(MessageStatus.skipped, "Контакт клиента не подтверждён — сведения о долге не отправляются")
    msg.address_masked = masked

    policy = get_policy(db)
    earliest = now
    if msg.purpose == NotificationEvent.overdue and client.party_type in LIMITED_PARTIES:
        earliest = frequency_wait_until(db, client.id, policy, now)
    earliest = next_allowed_time(policy, client.timezone, earliest)
    if earliest > now + timedelta(seconds=30):
        msg.scheduled_for = earliest
        msg.status_reason = "Перенесено на допустимое время по правилам связи с клиентом"
        enqueue(db, "send_message", {"message_id": str(msg.id)}, run_at=earliest,
                dedupe_key=f"send:{msg.id}:{int(earliest.timestamp())}")
        return

    subject, _ = render(msg.purpose, contract.number or "", msg.context)
    msg.attempts += 1
    try:
        provider_id = provider.send(address, subject, msg.body)
    except (ProviderError, OSError) as e:
        if msg.attempts < MAX_SEND_ATTEMPTS:
            retry_at = now + timedelta(minutes=5 * 2 ** msg.attempts)
            msg.status_reason = f"Ошибка доставки, повтор в {retry_at:%H:%M} UTC: {e}"
            enqueue(db, "send_message", {"message_id": str(msg.id)}, run_at=retry_at,
                    dedupe_key=f"send:{msg.id}:retry{msg.attempts}")
            return
        finish(MessageStatus.failed, f"Не доставлено после {msg.attempts} попыток: {e}")
        notify_staff(db, "message.failed", f"Не удалось связаться с клиентом {client.full_name}",
                     f"Канал: {msg.channel.value}. Договор № {contract.number}.", f"/contracts/{contract.id}")
        from app.services.staff_tasks import open_task
        open_task(db, "contact_failed", f"Связаться с клиентом {client.full_name}: сообщение не доставлено",
                  f"Канал {msg.channel.value}: {e}", f"/contracts/{contract.id}", f"contact_failed:{msg.id}",
                  due=_local_date(now))
        return
    msg.status = MessageStatus.sent
    msg.sent_at = now
    msg.provider = provider.name
    msg.provider_message_id = provider_id
    msg.status_reason = "Тестовый режим: записано в журнал, наружу не отправлено" if provider.test_mode else ""


def message_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(OutboundMessage.status, func.count()).group_by(OutboundMessage.status)).all()
    return {status.value: count for status, count in rows}
