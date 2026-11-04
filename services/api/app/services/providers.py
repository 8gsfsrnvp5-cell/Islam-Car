"""Каналы доставки сообщений.

SMS отправляется через SMS.ru — после договора с оператором и согласования имени отправителя.
Пока SMS-поставщик не настроен, канал SMS считается недоступным и сообщения не отправляются.
Режим "log" нужен для разработки: сообщение пишется в журнал, наружу ничего не уходит.
"""

import re
import smtplib
import uuid
from email.message import EmailMessage
from typing import Protocol

from app.config import get_settings
from app.models import Channel
from app.services.http import HttpError, request_json

SMSRU_URL = "https://sms.ru/sms/send"


class ProviderError(Exception):
    pass


class Provider(Protocol):
    name: str
    test_mode: bool

    def send(self, to: str, subject: str, body: str) -> str: ...


class LogProvider:
    """Тестовый режим: ничего не отправляет. В production не используется."""

    test_mode = True

    def __init__(self, channel: str) -> None:
        self.name = f"log-{channel}"

    def send(self, to: str, subject: str, body: str) -> str:
        return f"log-{uuid.uuid4().hex[:12]}"


class SmtpProvider:
    name = "smtp"
    test_mode = False

    def send(self, to: str, subject: str, body: str) -> str:
        s = get_settings()
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
                if s.smtp_starttls:
                    smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            raise ProviderError(f"SMTP: {e}") from e
        return msg.get("Message-ID", "") or uuid.uuid4().hex


class SmsRuProvider:
    """SMS.ru. Реализовано по документации https://sms.ru/api/send, на реальном аккаунте не проверялось."""

    name = "smsru"

    def __init__(self) -> None:
        self.test_mode = get_settings().smsru_test

    @staticmethod
    def phone(to: str) -> str:
        digits = re.sub(r"\D", "", to)
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        if not re.fullmatch(r"7\d{10}", digits):
            raise ProviderError("SMS.ru: номер должен быть российским (+7 и 10 цифр)")
        return digits

    def send(self, to: str, subject: str, body: str) -> str:
        s = get_settings()
        phone = self.phone(to)
        form = {"api_id": s.smsru_api_id, "to": phone, "msg": body, "json": 1}
        if s.smsru_from:
            form["from"] = s.smsru_from
        if self.test_mode:
            form["test"] = 1
        try:
            resp = request_json("POST", SMSRU_URL, form=form)
        except HttpError as e:
            raise ProviderError(f"SMS.ru: {e}") from e
        if not isinstance(resp, dict) or resp.get("status") != "OK":
            raise ProviderError(f"SMS.ru: {resp.get('status_text') if isinstance(resp, dict) else resp}")
        item = (resp.get("sms") or {}).get(phone) or {}
        if item.get("status") != "OK":
            raise ProviderError(f"SMS.ru: {item.get('status_text') or 'сообщение не принято'}")
        return str(item.get("sms_id") or uuid.uuid4().hex)


def get_provider(channel: Channel) -> Provider | None:
    """None — канал не подключён, сообщения по нему не отправляются."""
    s = get_settings()
    if channel == Channel.sms:
        if s.sms_provider == "log" and not s.is_production:
            return LogProvider("sms")
        # Тестовый режим SMS.ru ничего не доставляет — в production так сообщения считались бы отправленными
        if s.sms_provider == "smsru" and s.smsru_api_id and not (s.is_production and s.smsru_test):
            return SmsRuProvider()
        return None
    if channel == Channel.email:
        if s.email_provider == "log" and not s.is_production:
            return LogProvider("email")
        if s.email_provider == "smtp" and s.smtp_host and s.smtp_from:
            return SmtpProvider()
        return None
    return None


def channel_status() -> list[dict]:
    rows = [{"channel": "internal", "connected": True, "provider": "личный кабинет", "test_mode": False}]
    for ch in (Channel.sms, Channel.email):
        p = get_provider(ch)
        rows.append({"channel": ch.value, "connected": p is not None,
                     "provider": p.name if p else "", "test_mode": bool(p and p.test_mode),
                     "note": "реализовано по документации, проверьте на своём аккаунте" if p and p.name == "smsru"
                     else ""})
    return rows
