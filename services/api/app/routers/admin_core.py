"""Главная панель, поиск, уведомления, отчёты, настройки, сотрудники, журнал."""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Application,
    Audience,
    AuditLog,
    Car,
    Client,
    Contract,
    ContractStatus,
    Notification,
    Payment,
    Role,
    User,
)
from app.schemas import CompanySettingsIn, StaffUserIn
from app.security import Actor, check_password_strength, hash_password, require
from app.services import audit
from app.services.contracts import get_company, ledger_for
from app.services.dashboard import build_dashboard
from app.services.export import csv_response, money

router = APIRouter(prefix="/api/admin", tags=["admin: core"])

PAYMENT_METHOD_RU = {"bank_transfer": "Банковский перевод", "cash": "Наличные", "card": "Карта", "other": "Другое"}
CONTRACT_STATUS_RU = {"draft": "Черновик", "signed": "Действует", "completed": "Исполнен", "cancelled": "Отменён"}


@router.get("/dashboard")
def dashboard(date_from: date | None = None, date_to: date | None = None,
              actor: Actor = Depends(require("dashboard.read")), db: Session = Depends(get_db)):
    return build_dashboard(db, actor, date_from, date_to)


@router.get("/search")
def search(q: str, actor: Actor = Depends(require("dashboard.read")), db: Session = Depends(get_db)):
    """Глобальный поиск по ФИО, телефону, VIN, номеру договора и автомобилю — в пределах прав."""
    q = q.strip()
    if len(q) < 2:
        return {"clients": [], "cars": [], "contracts": [], "applications": []}
    like = f"%{q.lower()}%"
    digits = "".join(ch for ch in q if ch.isdigit())
    phone_like = f"%{digits[-10:]}%" if len(digits) >= 4 else None
    result: dict[str, list] = {"clients": [], "cars": [], "contracts": [], "applications": []}

    if actor.can("clients.read"):
        conds = [func.lower(Client.full_name).like(like)]
        if phone_like:
            conds.append(Client.phone.like(phone_like))
        result["clients"] = [{"id": c.id, "title": c.full_name, "subtitle": c.phone if actor.can("clients.pd") else ""}
                             for c in db.scalars(select(Client).where(or_(*conds)).limit(10))]
    if actor.can("cars.read"):
        result["cars"] = [{"id": c.id, "title": f"{c.make} {c.model}, {c.year}", "subtitle": c.vin or "VIN не указан"}
                          for c in db.scalars(select(Car).where(or_(
                              func.lower(Car.vin).like(like), func.lower(Car.make).like(like),
                              func.lower(Car.model).like(like),
                              func.lower(Car.make + " " + Car.model).like(like))).limit(10))]
    if actor.can("contracts.read"):
        stmt = select(Contract).join(Client).join(Car).where(or_(
            func.lower(Contract.number).like(like), func.lower(Client.full_name).like(like),
            func.lower(Car.vin).like(like), func.lower(Car.model).like(like),
            *([Client.phone.like(phone_like)] if phone_like else []))).limit(10)
        for c in db.scalars(stmt):
            subtitle = f"{c.client.full_name} · {c.car.make} {c.car.model}"
            if c.status in (ContractStatus.signed, ContractStatus.completed):
                lg = ledger_for(db, c)
                if lg.overdue_kopecks:
                    subtitle += " · просрочка"
                elif lg.outstanding_kopecks == 0:
                    subtitle += " · оплачен"
            result["contracts"].append({"id": c.id, "title": f"Договор № {c.number or 'черновик'}",
                                        "subtitle": subtitle, "status": c.status})
    if actor.can("applications.read"):
        conds = [func.lower(Application.name).like(like)]
        if phone_like:
            conds.append(Application.phone.like(phone_like))
        result["applications"] = [{"id": a.id, "title": f"Заявка: {a.name}", "subtitle": a.status}
                                  for a in db.scalars(select(Application).where(or_(*conds)).limit(10))]
    return result


# --- Уведомления сотрудникам ---

@router.get("/notifications")
def staff_notifications(unread: bool = False, actor: Actor = Depends(require("notifications.read")),
                        db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.audience == Audience.staff) \
        .order_by(Notification.created_at.desc()).limit(200)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
             "created_at": n.created_at, "read": n.read_at is not None} for n in db.scalars(stmt).all()]


@router.get("/notifications/unread-count")
def unread_count(actor: Actor = Depends(require("notifications.read")), db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.audience == Audience.staff, Notification.read_at.is_(None))) or 0
    latest = db.scalar(select(Notification).where(Notification.audience == Audience.staff)
                       .order_by(Notification.created_at.desc()).limit(1))
    return {"unread": count, "latest_id": latest.id if latest else None,
            "latest_title": latest.title if latest else None}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, actor: Actor = Depends(require("notifications.read")),
              db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if not n or n.audience != Audience.staff:
        raise HTTPException(404, "Уведомление не найдено")
    n.read_at = n.read_at or datetime.now(UTC)
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(actor: Actor = Depends(require("notifications.read")), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.audience == Audience.staff,
                                                   Notification.read_at.is_(None))):
        n.read_at = datetime.now(UTC)
    db.commit()
    return {"ok": True}


# --- Отчёты (CSV для Excel) ---

@router.get("/reports/contracts.csv")
def contracts_csv(actor: Actor = Depends(require("reports.read")), db: Session = Depends(get_db)):
    rows = [["Номер", "Статус", "Покупатель", "Автомобиль", "VIN", "Дата подписания", "Цена, руб.",
             "Закупка, руб.", "Наценка, руб.", "Взнос, руб.", "Срок, мес.", "Оплачено, руб.", "Остаток, руб.",
             "Просрочено, руб."]]
    for c in db.scalars(select(Contract).where(Contract.status.in_([ContractStatus.signed, ContractStatus.completed]))
                        .order_by(Contract.signed_at)):
        lg = ledger_for(db, c)
        rows.append([c.number, CONTRACT_STATUS_RU[c.status.value], c.client.full_name,
                     f"{c.car.make} {c.car.model} {c.car.year}", c.car.vin or "",
                     f"{c.signed_at:%d.%m.%Y}" if c.signed_at else "", money(c.sale_price_kopecks),
                     money(c.purchase_price_kopecks), money(c.markup_kopecks), money(c.down_payment_kopecks),
                     str(c.term_months), money(lg.paid_kopecks), money(lg.outstanding_kopecks),
                     money(lg.overdue_kopecks)])
    return csv_response(rows, "contracts.csv")


@router.get("/reports/payments.csv")
def payments_csv(date_from: date | None = None, date_to: date | None = None,
                 actor: Actor = Depends(require("reports.read")), db: Session = Depends(get_db)):
    stmt = select(Payment, Contract).join(Contract, Contract.id == Payment.contract_id).order_by(Payment.received_on)
    if date_from:
        stmt = stmt.where(Payment.received_on >= date_from)
    if date_to:
        stmt = stmt.where(Payment.received_on <= date_to)
    rows = [["Дата поступления", "Договор", "Покупатель", "Сумма, руб.", "Способ", "Документ", "Статус",
             "Причина сторно"]]
    for p, c in db.execute(stmt).all():
        rows.append([f"{p.received_on:%d.%m.%Y}", c.number, c.client.full_name, money(p.amount_kopecks),
                     PAYMENT_METHOD_RU[p.method.value], p.document_ref,
                     "Учтён" if p.status.value == "confirmed" else "Сторнирован", p.reversal_reason])
    return csv_response(rows, "payments.csv")


# --- Настройки компании ---

def settings_dict(s) -> dict:
    return {k: getattr(s, k) for k in CompanySettingsIn.model_fields} | {"next_contract_seq": s.next_contract_seq}


@router.get("/settings")
def read_settings(actor: Actor = Depends(require("dashboard.read")), db: Session = Depends(get_db)):
    s = get_company(db)
    db.commit()
    return settings_dict(s)


@router.put("/settings")
def write_settings(data: CompanySettingsIn, actor: Actor = Depends(require("settings.write")),
                   db: Session = Depends(get_db)):
    s = get_company(db)
    before = settings_dict(s)
    for key, value in data.model_dump().items():
        setattr(s, key, value)
    audit.record(db, actor, "settings.updated", "settings", 1, before=before, after=data.model_dump())
    db.commit()
    return settings_dict(s)


# --- Сотрудники ---

def user_dict(u: User) -> dict:
    return {"id": u.id, "login": u.login, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
            "totp_enabled": u.totp_enabled, "last_login_at": u.last_login_at, "created_at": u.created_at}


@router.get("/users")
def list_users(actor: Actor = Depends(require("users.manage")), db: Session = Depends(get_db)):
    return [user_dict(u) for u in db.scalars(select(User).where(User.role != Role.client).order_by(User.created_at))]


@router.post("/users", status_code=201)
def create_user(data: StaffUserIn, actor: Actor = Depends(require("users.manage")), db: Session = Depends(get_db)):
    if data.role == Role.client:
        raise HTTPException(422, "Доступ покупателей выдаётся из карточки клиента")
    login = data.login.lower()
    if db.scalar(select(User.id).where(User.login == login)):
        raise HTTPException(409, "Такой логин уже существует")
    check_password_strength(data.password)
    u = User(login=login, full_name=data.full_name, role=data.role, password_hash=hash_password(data.password))
    db.add(u)
    db.flush()
    audit.record(db, actor, "user.created", "user", u.id, login=login, role=data.role)
    db.commit()
    return user_dict(u)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: uuid.UUID, actor: Actor = Depends(require("users.manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u or u.role == Role.client:
        raise HTTPException(404, "Сотрудник не найден")
    if u.id == actor.user.id:
        raise HTTPException(409, "Нельзя отключить собственную учётную запись")
    u.is_active = False
    audit.record(db, actor, "user.deactivated", "user", u.id)
    db.commit()
    return user_dict(u)


# --- Журнал действий ---

@router.get("/audit")
def audit_log(entity_id: str | None = None, limit: int = 200, actor: Actor = Depends(require("audit.read")),
              db: Session = Depends(get_db)):
    stmt = select(AuditLog, User).outerjoin(User, User.id == AuditLog.actor_user_id) \
        .order_by(AuditLog.created_at.desc()).limit(min(limit, 1000))
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    return [{"id": a.id, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
             "data": a.data, "actor": u.full_name if u else "Система/клиент", "actor_role": a.actor_role,
             "ip": a.ip, "created_at": a.created_at} for a, u in db.execute(stmt).all()]
