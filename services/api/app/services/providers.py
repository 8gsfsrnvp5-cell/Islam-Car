"""Каналы доставки сообщений.

Реальный SMS-поставщик подключается отдельно (договор с официальным оператором рассылок).
Пока он не подключён, канал SMS считается недоступным и сообщения не отправляются.
Режим "log" нужен для разработки: сообщение пишется в журнал, наружу ничего не уходит.
"""

import smtplib
import uuid
from email.message import EmailMessage
from typing import Protocol

from app.config import get_settings
from app.models import Channel


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


def get_provider(channel: Channel) -> Provider | None:
    """None — канал не подключён, сообщения по нему не отправляются."""
    s = get_settings()
    if channel == Channel.sms:
        if s.sms_provider == "log" and not s.is_production:
            return LogProvider("sms")
        return None  # официальный SMS-поставщик подключается в отдельной задаче
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
                     "provider": p.name if p else "", "test_mode": bool(p and p.test_mode)})
    return rows
