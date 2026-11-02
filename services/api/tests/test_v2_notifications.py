"""Версия 2: напоминания, согласия, время и частота сообщений, повторы, устойчивость к перезапуску."""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Contract, Job, JobStatus, MessageStatus, NotificationEvent, OutboundMessage, StaffTask
from app.services import messaging
from app.services.common import today
from app.services.providers import ProviderError
from app.worker.queue import enqueue
from app.worker.runner import run_once
from tests.helpers import RUB, buyer_session, confirm_payment, signed_deal


def at(hour_utc: int, day_offset: int = 0) -> datetime:
    """Момент времени в UTC для «сегодня» по часовому поясу компании (Москва = UTC+3)."""
    return datetime.combine(today() + timedelta(days=day_offset), time(hour_utc, 0), tzinfo=UTC)


def allow_channels(admin, client_id: str) -> None:
    admin.patch(f"/api/admin/clients/{client_id}", json={"email": "buyer@example.test"})
    for contact in ("phone", "email"):
        assert admin.post(f"/api/admin/clients/{client_id}/contacts/verify",
                          json={"contact": contact}).status_code == 200
    for channel in ("sms", "email"):
        r = admin.post(f"/api/admin/clients/{client_id}/consents",
                       json={"channel": channel, "granted": True, "source": "письменное согласие при заключении"})
        assert r.status_code == 200


def messages(contract_id: str) -> list[OutboundMessage]:
    with SessionLocal() as db:
        return list(db.scalars(select(OutboundMessage).where(OutboundMessage.contract_id == uuid.UUID(contract_id))
                               .order_by(OutboundMessage.created_at)))


def test_due_day_reminders_sent_once_through_allowed_channels(admin):
    _, client, contract = signed_deal(admin)  # первоначальный взнос — сегодня
    allow_channels(admin, client["id"])
    run_once(at(9))  # 12:00 по Москве

    due = [m for m in messages(contract["id"]) if m.purpose == NotificationEvent.due_day]
    assert {m.channel.value: m.status.value for m in due} == {"internal": "sent", "sms": "sent", "email": "sent"}
    sms = next(m for m in due if m.channel.value == "sms")
    assert sms.body.startswith("Islamic Car. Сегодня, ") and "600 000 рублей" in sms.body
    assert sms.address_masked.endswith("33") and "9001112233" not in sms.address_masked
    assert "Тестовый режим" in sms.status_reason  # наружу в тестах ничего не уходит

    run_once(at(10))  # повторный проход не создаёт дублей
    assert len([m for m in messages(contract["id"]) if m.purpose == NotificationEvent.due_day]) == 3


def test_before_due_text_matches_business_example(admin):
    _, client, contract = signed_deal(admin, contract_date=today() - timedelta(days=25))
    confirm_payment(admin, contract["id"], 600_000)  # взнос внесён, следующий платёж через 5 дней
    allow_channels(admin, client["id"])
    run_once(at(9))
    sms = next(m for m in messages(contract["id"])
               if m.purpose == NotificationEvent.before_due and m.channel.value == "sms")
    due = today() + timedelta(days=5)
    expected = (f"Islamic Car. Напоминаем, что {messaging.day_month(due)} по договору № {contract['number']} "
                f"ожидается платёж 50 000 рублей. Информация доступна в вашем личном кабинете.")
    assert sms.body == expected and sms.status == MessageStatus.sent


def test_paid_installment_does_not_trigger_reminder(admin):
    """Сценарий 13: напоминание, запланированное ночью, отменяется, если платёж поступил до отправки."""
    _, client, contract = signed_deal(admin, contract_date=today() + timedelta(days=1) - timedelta(days=30))
    confirm_payment(admin, contract["id"], 600_000)
    allow_channels(admin, client["id"])

    run_once(at(20))  # 23:00 по Москве — писать клиенту нельзя, SMS переносится на утро
    sms = next(m for m in messages(contract["id"])
               if m.purpose == NotificationEvent.before_due and m.channel.value == "sms")
    assert sms.status == MessageStatus.scheduled and "допустимое время" in sms.status_reason

    confirm_payment(admin, contract["id"], 50_000, doc="п/п 2")  # покупатель оплатил заранее
    run_once(at(7, day_offset=1))  # 10:00 следующего дня
    sms = next(m for m in messages(contract["id"]) if m.id == sms.id)
    assert sms.status == MessageStatus.cancelled and "уже поступил" in sms.status_reason


def test_without_consent_or_verified_contact_nothing_is_sent(admin):
    _, client, contract = signed_deal(admin)
    run_once(at(9))
    external = {m.channel.value: m for m in messages(contract["id"]) if m.channel.value != "internal"}
    assert external["sms"].status == MessageStatus.skipped and "согласия" in external["sms"].status_reason

    admin.post(f"/api/admin/clients/{client['id']}/consents",
               json={"channel": "sms", "granted": True, "source": "заявление"})
    with SessionLocal() as db:
        c = db.get(Contract, uuid.UUID(contract["id"]))
        messaging.create_messages(db, c, NotificationEvent.due_day, "manual-check",
                                  {"seq": 0, "due_date": today().isoformat(), "amount_kopecks": 600_000 * RUB,
                                   "schedule_version": 1}, ["sms"], at(9))
        db.commit()
    run_once(at(9), periodic=False)
    manual = next(m for m in messages(contract["id"]) if "manual-check" in m.event_key)
    assert manual.status == MessageStatus.skipped and "не подтверждён" in manual.status_reason


def test_overdue_frequency_limit_reschedules(admin):
    _, client, contract = signed_deal(admin, contract_date=today() - timedelta(days=40))
    allow_channels(admin, client["id"])
    now = at(9)
    with SessionLocal() as db:
        c = db.get(Contract, uuid.UUID(contract["id"]))
        for i in range(3):
            messaging.create_messages(db, c, NotificationEvent.overdue, f"limit-{i}",
                                      {"seq": 0, "due_date": c.contract_date.isoformat(),
                                       "amount_kopecks": 1, "schedule_version": 1}, ["sms"], now)
        db.commit()
    run_once(now, periodic=False)
    statuses = sorted(m.status.value for m in messages(contract["id"]) if "limit-" in m.event_key)
    # Не больше двух сообщений о просрочке в сутки (параметр политики по 230-ФЗ)
    assert statuses == ["scheduled", "sent", "sent"]
    overdue_text = next(m for m in messages(contract["id"]) if m.status == MessageStatus.sent).body
    assert "Проценты и штрафы не начисляются" in overdue_text


def test_quiet_hours_respect_client_timezone():
    policy = dict(messaging.DEFAULT_POLICY)
    monday_night_utc = datetime(2026, 11, 2, 20, 0, tzinfo=UTC)  # 23:00 в Москве, 05:00 во Владивостоке
    assert messaging.next_allowed_time(policy, "Europe/Moscow", monday_night_utc) == datetime(2026, 11, 3, 5, 0,
                                                                                             tzinfo=UTC)
    assert messaging.next_allowed_time(policy, "Asia/Vladivostok", monday_night_utc) == datetime(2026, 11, 2, 22, 0,
                                                                                               tzinfo=UTC)
    saturday_morning = datetime(2026, 11, 7, 5, 30, tzinfo=UTC)  # 08:30 в субботу — ещё рано
    assert messaging.next_allowed_time(policy, "Europe/Moscow", saturday_morning) == datetime(2026, 11, 7, 6, 0,
                                                                                            tzinfo=UTC)
    policy["holidays"] = ["2026-11-04"]  # праздничный день как выходной
    holiday = datetime(2026, 11, 4, 5, 30, tzinfo=UTC)
    assert messaging.next_allowed_time(policy, "Europe/Moscow", holiday) == datetime(2026, 11, 4, 6, 0, tzinfo=UTC)


def test_payment_confirmation_message_and_reversal_cancels_it(admin):
    _, client, contract = signed_deal(admin)
    allow_channels(admin, client["id"])
    buyer = buyer_session(admin, client["id"])
    payment = confirm_payment(admin, contract["id"], 600_000)
    titles = [n["title"] for n in buyer.get("/api/client/notifications").json()]
    assert f"Платёж 600 000 рублей по договору № {contract['number']} получен и учтён" in titles

    confirmed = [m for m in messages(contract["id"]) if m.purpose == NotificationEvent.payment_confirmed]
    assert {m.channel.value for m in confirmed} == {"internal", "sms", "email"}
    admin.post(f"/api/admin/payments/{payment['id']}/reverse", json={"reason": "Ошибочно учтён"})
    run_once(datetime.now(UTC) + timedelta(seconds=5), periodic=False)  # отмена — до проверки времени
    sms = next(m for m in messages(contract["id"])
               if m.purpose == NotificationEvent.payment_confirmed and m.channel.value == "sms")
    assert sms.status == MessageStatus.cancelled and "сторнирован" in sms.status_reason


def test_delivery_failure_is_retried_then_reported(admin, monkeypatch):
    class Broken:
        name, test_mode = "broken", False

        def send(self, to, subject, body):
            raise ProviderError("оператор недоступен")

    monkeypatch.setattr(messaging, "get_provider", lambda channel: Broken())
    _, client, contract = signed_deal(admin)
    allow_channels(admin, client["id"])
    now = at(9)
    run_once(now)
    run_once(now + timedelta(minutes=11), periodic=False)
    run_once(now + timedelta(minutes=40), periodic=False)
    sms = next(m for m in messages(contract["id"])
               if m.purpose == NotificationEvent.due_day and m.channel.value == "sms")
    assert sms.status == MessageStatus.failed and sms.attempts == 3
    notes = admin.get("/api/admin/notifications").json()
    assert any("Не удалось связаться" in n["title"] for n in notes)
    with SessionLocal() as db:
        assert db.scalar(select(StaffTask).where(StaffTask.kind == "contact_failed"))


def test_jobs_survive_worker_crash():
    """Сценарий 20: задача, взятая упавшим обработчиком, возвращается в очередь и выполняется."""
    now = at(9)
    with SessionLocal() as db:
        job = enqueue(db, "staff_scan", {}, now, dedupe_key="crash-test")
        job.status = JobStatus.running
        job.locked_until = now - timedelta(minutes=1)
        db.commit()
        job_id = job.id
    run_once(now, periodic=False)
    with SessionLocal() as db:
        assert db.get(Job, job_id).status == JobStatus.done


def test_notification_settings_api(admin):
    data = admin.get("/api/admin/notification-settings").json()
    assert {(r["event"], r["offset_days"]) for r in data["rules"]} >= {("before_due", 5), ("payment_confirmed", 0)}
    assert {c["channel"]: c["connected"] for c in data["channels"]}["sms"] is True  # тестовый режим
    policy = {**{k: v for k, v in data["policy"].items() if k != "basis"}, "overdue_per_day": 1,
              "holidays": ["2027-01-01"]}
    assert admin.put("/api/admin/notification-settings/policy", json=policy).json()["policy"]["overdue_per_day"] == 1
    rules = [{**r, "enabled": r["event"] != "overdue"} for r in data["rules"]]
    saved = admin.put("/api/admin/notification-settings/rules", json={"rules": rules}).json()["rules"]
    assert not any(r["enabled"] for r in saved if r["event"] == "overdue")


def test_owner_must_enable_second_factor_when_required(admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "require_owner_2fa", True)
    assert admin.get("/api/admin/dashboard").json()["detail"] == "owner_2fa_required"
    assert admin.get("/api/auth/admin/me").json()["two_factor_required"] is True
    import pyotp
    secret = admin.post("/api/auth/admin/totp/setup").json()["secret"]
    admin.post("/api/auth/admin/totp/enable", json={"code": pyotp.TOTP(secret).now()})
    assert admin.get("/api/admin/dashboard").status_code == 200


def test_buyer_manages_own_consents(admin):
    _, client, _ = signed_deal(admin)
    buyer = buyer_session(admin, client["id"])
    channels = {c["channel"]: c for c in buyer.post("/api/client/communications",
                                                     json={"channel": "sms", "granted": True}).json()["channels"]}
    assert channels["sms"]["granted"] is True
    staff_view = admin.get(f"/api/admin/clients/{client['id']}/communications").json()
    assert staff_view["consents"]["sms"]["source"] == "личный кабинет"
    buyer.post("/api/client/communications", json={"channel": "sms", "granted": False})
    assert admin.get(f"/api/admin/clients/{client['id']}/communications").json()["consents"]["sms"]["granted"] is False


@pytest.mark.parametrize("kopecks,text", [(5_000_000, "50 000 рублей"), (100, "1 рубль"), (250, "2 рубля 50 копеек"),
                                          (2_100, "21 рубль")])
def test_amounts_in_words(kopecks, text):
    assert messaging.rub_words(kopecks) == text
