"""Внутренние уведомления (версия 1). SMS, e-mail и мессенджеры — версия 2, через services/workers."""

import uuid

from sqlalchemy.orm import Session

from app.models import Audience, Notification


def notify_staff(db: Session, kind: str, title: str, body: str = "", link: str = "") -> None:
    db.add(Notification(audience=Audience.staff, kind=kind, title=title, body=body, link=link))


def notify_client(db: Session, client_id: uuid.UUID, kind: str, title: str, body: str = "", link: str = "") -> None:
    db.add(Notification(audience=Audience.client, client_id=client_id, kind=kind, title=title, body=body, link=link))


def rub(kopecks: int) -> str:
    rubles, kop = divmod(kopecks, 100)
    text = f"{rubles:,}".replace(",", " ")
    return f"{text},{kop:02d} ₽" if kop else f"{text} ₽"
