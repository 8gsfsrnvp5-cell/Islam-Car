"""Заявки, клиенты, доступ в личный кабинет, обращения."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    ActivationToken,
    Application,
    ApplicationEvent,
    ApplicationKind,
    ApplicationStatus,
    Client,
    Contract,
    ContractStatus,
    Role,
    SupportMessage,
    SupportThread,
    ThreadStatus,
    User,
)
from app.schemas import ApplicationStatusIn, ClientIn, ClientPatch, MessageIn
from app.security import Actor, hash_token, new_token, require
from app.serializers import application_staff, client_staff, contract_staff, thread_dict
from app.services import audit
from app.services.common import normalize_phone
from app.services.contracts import ledger_for
from app.services.notify import notify_client

router = APIRouter(prefix="/api/admin", tags=["admin: crm"])

ACTIVATION_TTL_HOURS = 72
FINAL_APP_STATUSES = (ApplicationStatus.converted, ApplicationStatus.rejected, ApplicationStatus.withdrawn)


# --- Заявки -------------------------------------------------------------------

def get_application(db: Session, app_id: uuid.UUID) -> Application:
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404, "Заявка не найдена")
    return a


@router.get("/applications")
def list_applications(status: ApplicationStatus | None = None, kind: ApplicationKind | None = None,
                      actor: Actor = Depends(require("applications.read")), db: Session = Depends(get_db)):
    stmt = select(Application).order_by(Application.created_at.desc()).limit(500)
    if status:
        stmt = stmt.where(Application.status == status)
    if kind:
        stmt = stmt.where(Application.kind == kind)
    return [application_staff(a) for a in db.scalars(stmt).all()]


@router.get("/applications/{app_id}")
def read_application(app_id: uuid.UUID, actor: Actor = Depends(require("applications.read")),
                     db: Session = Depends(get_db)):
    return application_staff(get_application(db, app_id))


@router.post("/applications/{app_id}/status")
def change_application_status(app_id: uuid.UUID, data: ApplicationStatusIn,
                              actor: Actor = Depends(require("applications.write")), db: Session = Depends(get_db)):
    a = get_application(db, app_id)
    if a.status in FINAL_APP_STATUSES:
        raise HTTPException(409, "Заявка закрыта, статус изменить нельзя")
    if data.status in (ApplicationStatus.converted, ApplicationStatus.withdrawn, ApplicationStatus.new):
        raise HTTPException(422, "Этот статус выставляется автоматически")
    if data.status == ApplicationStatus.rejected and not data.public_message:
        raise HTTPException(422, "При отказе укажите сообщение для клиента")
    db.add(ApplicationEvent(application_id=a.id, from_status=a.status.value, to_status=data.status.value,
                            public_message=data.public_message, actor_user_id=actor.user.id))
    before = a.status
    a.status = data.status
    if data.public_message:
        a.public_message = data.public_message
    if data.internal_note is not None:
        a.internal_note = data.internal_note
    if a.assigned_to is None:
        a.assigned_to = actor.user.id
    if a.client_id:
        notify_client(db, a.client_id, "application.status", "Статус вашей заявки изменён",
                      data.public_message, "/cabinet")
    audit.record(db, actor, "application.status", "application", a.id, before=before, after=data.status)
    db.commit()
    return application_staff(a)


@router.post("/applications/{app_id}/client")
def client_from_application(app_id: uuid.UUID, actor: Actor = Depends(require("clients.write")),
                            db: Session = Depends(get_db)):
    """Создаёт карточку клиента по заявке или привязывает существующую с тем же телефоном."""
    a = get_application(db, app_id)
    if a.client_id:
        return {"client_id": a.client_id, "created": False}
    client = db.scalar(select(Client).where(Client.phone == a.phone))
    created = client is None
    if created:
        client = Client(full_name=a.name, phone=a.phone)
        db.add(client)
        db.flush()
        audit.record(db, actor, "client.created", "client", client.id, source="application", application=a.id)
    a.client_id = client.id
    db.commit()
    return {"client_id": client.id, "created": created}


# --- Клиенты ------------------------------------------------------------------

def get_client(db: Session, client_id: uuid.UUID) -> Client:
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(404, "Клиент не найден")
    return c


@router.get("/clients")
def list_clients(q: str = "", actor: Actor = Depends(require("clients.read")), db: Session = Depends(get_db)):
    stmt = select(Client).order_by(Client.created_at.desc()).limit(500)
    if q:
        like = f"%{q.lower()}%"
        digits = "".join(ch for ch in q if ch.isdigit())
        conds = [func.lower(Client.full_name).like(like), func.lower(Client.email).like(like)]
        if len(digits) >= 4:
            conds.append(Client.phone.like(f"%{digits[-10:]}%"))
        stmt = stmt.where(or_(*conds))
    return [client_staff(c, actor) for c in db.scalars(stmt).all()]


@router.post("/clients", status_code=201)
def create_client(data: ClientIn, actor: Actor = Depends(require("clients.write")), db: Session = Depends(get_db)):
    values = data.model_dump()
    values["phone"] = normalize_phone(values["phone"])
    if db.scalar(select(Client.id).where(Client.phone == values["phone"])):
        raise HTTPException(409, "Клиент с таким телефоном уже есть в реестре")
    client = Client(**values)
    db.add(client)
    db.flush()
    audit.record(db, actor, "client.created", "client", client.id)
    db.commit()
    return client_staff(client, actor)


@router.get("/clients/{client_id}")
def read_client(client_id: uuid.UUID, actor: Actor = Depends(require("clients.read")), db: Session = Depends(get_db)):
    c = get_client(db, client_id)
    data = client_staff(c, actor)
    contracts = db.scalars(select(Contract).where(Contract.client_id == c.id)
                           .order_by(Contract.created_at.desc())).all()
    live = (ContractStatus.signed, ContractStatus.completed)
    data["contracts"] = [contract_staff(k, ledger_for(db, k) if k.status in live else None, actor, with_rows=False)
                         for k in contracts]
    data["applications"] = [application_staff(a) for a in db.scalars(
        select(Application).where(Application.client_id == c.id).order_by(Application.created_at.desc()))]
    data["threads"] = [thread_dict(t, with_messages=False, for_staff=True) for t in db.scalars(
        select(SupportThread).where(SupportThread.client_id == c.id).order_by(SupportThread.updated_at.desc()))]
    return data


PD_FIELDS = {"birth_date", "passport_number", "passport_issued_by", "passport_issue_date", "address", "phone"}


@router.patch("/clients/{client_id}")
def update_client(client_id: uuid.UUID, data: ClientPatch, actor: Actor = Depends(require("clients.write")),
                  db: Session = Depends(get_db)):
    c = get_client(db, client_id)
    changes = data.model_dump(exclude_unset=True)
    if "phone" in changes:
        changes["phone"] = normalize_phone(changes["phone"])
        dup = db.scalar(select(Client.id).where(Client.phone == changes["phone"], Client.id != c.id))
        if dup:
            raise HTTPException(409, "Клиент с таким телефоном уже есть в реестре")
    if PD_FIELDS & changes.keys() and not actor.can("clients.pd"):
        raise HTTPException(403, "Недостаточно прав для изменения персональных данных")
    identity_fields = {"full_name", "passport_number", "passport_issued_by", "passport_issue_date", "birth_date",
                       "party_type", "inn", "ogrn"}
    reset_verification = c.identity_verified and any(
        k in identity_fields and getattr(c, k) != v for k, v in changes.items())
    for key, value in changes.items():
        setattr(c, key, value)
    if reset_verification:
        # Изменились данные личности — проверку нужно провести заново
        c.identity_verified = False
        c.identity_verified_at = None
        c.identity_verified_by = None
    # В журнал пишем только список полей, без самих персональных данных
    audit.record(db, actor, "client.updated", "client", c.id, fields=sorted(changes),
                 verification_reset=reset_verification)
    db.commit()
    return client_staff(c, actor)


@router.post("/clients/{client_id}/verify")
def verify_client(client_id: uuid.UUID, actor: Actor = Depends(require("clients.verify")),
                  db: Session = Depends(get_db)):
    """Сотрудник подтверждает, что личность проверена по оригиналу документа."""
    c = get_client(db, client_id)
    c.identity_verified = True
    c.identity_verified_at = datetime.now(UTC)
    c.identity_verified_by = actor.user.id
    audit.record(db, actor, "client.identity_verified", "client", c.id)
    db.commit()
    return client_staff(c, actor)


@router.post("/clients/{client_id}/access")
def issue_cabinet_access(client_id: uuid.UUID, actor: Actor = Depends(require("clients.access")),
                         db: Session = Depends(get_db)):
    """Выдаёт одноразовую ссылку для установки пароля. Ссылку передают клиенту лично или по подтверждённому каналу."""
    c = get_client(db, client_id)
    if not c.identity_verified:
        raise HTTPException(409, "Сначала подтвердите личность клиента")
    has_contract = db.scalar(select(func.count()).select_from(Contract).where(
        Contract.client_id == c.id, Contract.status.in_([ContractStatus.signed, ContractStatus.completed])))
    if not has_contract:
        raise HTTPException(409, "Доступ выдаётся после подписания договора")
    user = c.user
    if user is None:
        if db.scalar(select(User.id).where(User.login == c.phone)):
            raise HTTPException(409, "Логин с таким телефоном уже занят")
        user = User(login=c.phone, full_name=c.full_name, role=Role.client, client_id=c.id, is_active=True)
        db.add(user)
        db.flush()
    # Старые неиспользованные ссылки аннулируются
    for old in db.scalars(select(ActivationToken).where(ActivationToken.user_id == user.id,
                                                        ActivationToken.used_at.is_(None))):
        old.used_at = datetime.now(UTC)
    token = new_token()
    db.add(ActivationToken(token_hash=hash_token(token), user_id=user.id, created_by=actor.user.id,
                           expires_at=datetime.now(UTC) + timedelta(hours=ACTIVATION_TTL_HOURS)))
    audit.record(db, actor, "client.access_issued", "client", c.id)
    db.commit()
    return {"activation_path": f"/activate?token={token}", "login": user.login,
            "expires_in_hours": ACTIVATION_TTL_HOURS}


# --- Обращения ------------------------------------------------------------------

def get_thread(db: Session, thread_id: uuid.UUID) -> SupportThread:
    t = db.get(SupportThread, thread_id)
    if not t:
        raise HTTPException(404, "Обращение не найдено")
    return t


@router.get("/threads")
def list_threads(status: ThreadStatus | None = None, actor: Actor = Depends(require("support.read")),
                 db: Session = Depends(get_db)):
    stmt = select(SupportThread).order_by(SupportThread.updated_at.desc()).limit(300)
    if status:
        stmt = stmt.where(SupportThread.status == status)
    return [thread_dict(t, with_messages=False, for_staff=True) for t in db.scalars(stmt).all()]


@router.get("/threads/{thread_id}")
def read_thread(thread_id: uuid.UUID, actor: Actor = Depends(require("support.read")), db: Session = Depends(get_db)):
    t = get_thread(db, thread_id)
    data = thread_dict(t, with_messages=True, for_staff=True)
    if t.contract_id:
        k = db.get(Contract, t.contract_id)
        data["contract"] = contract_staff(k, ledger_for(db, k), actor, with_rows=True)
    return data


@router.post("/threads/{thread_id}/messages", status_code=201)
def reply(thread_id: uuid.UUID, data: MessageIn, actor: Actor = Depends(require("support.write")),
          db: Session = Depends(get_db)):
    t = get_thread(db, thread_id)
    if t.status == ThreadStatus.closed:
        raise HTTPException(409, "Обращение закрыто")
    db.add(SupportMessage(thread_id=t.id, author_user_id=actor.user.id, from_staff=True, body=data.body))
    t.status = ThreadStatus.answered
    t.updated_at = datetime.now(UTC)
    notify_client(db, t.client_id, "support.reply", f"Ответ на обращение: {t.subject}", "",
                  f"/cabinet/support/{t.id}")
    audit.record(db, actor, "support.reply", "thread", t.id)
    db.commit()
    db.refresh(t)
    return thread_dict(t, with_messages=True, for_staff=True)


@router.post("/threads/{thread_id}/close")
def close_thread(thread_id: uuid.UUID, actor: Actor = Depends(require("support.write")),
                 db: Session = Depends(get_db)):
    t = get_thread(db, thread_id)
    t.status = ThreadStatus.closed
    t.updated_at = datetime.now(UTC)
    audit.record(db, actor, "support.closed", "thread", t.id)
    db.commit()
    return thread_dict(t, with_messages=True, for_staff=True)
