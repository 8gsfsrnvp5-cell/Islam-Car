from datetime import UTC, datetime

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ActivationToken, Realm, Role, User
from app.permissions import permissions_for
from app.schemas import ActivateIn, ChangePasswordIn, LoginIn, TotpCodeIn
from app.security import (
    Actor,
    as_aware,
    check_password_strength,
    client_ip,
    close_session,
    current_client,
    current_staff,
    ensure_not_throttled,
    hash_password,
    hash_token,
    open_session,
    record_attempt,
    verify_password,
)
from app.services import audit
from app.services.common import normalize_phone

router = APIRouter(prefix="/api/auth", tags=["auth"])

BAD_CREDENTIALS = "Неверный логин или пароль"


def staff_me(actor: Actor) -> dict:
    u = actor.user
    return {"id": u.id, "login": u.login, "full_name": u.full_name, "role": u.role,
            "totp_enabled": u.totp_enabled, "permissions": permissions_for(u.role),
            "two_factor_required": u.role == Role.owner and get_settings().owner_2fa_required}


@router.post("/admin/login")
def admin_login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    login = data.login.strip().lower()
    ip = client_ip(request)
    ensure_not_throttled(db, login, ip)
    user = db.scalar(select(User).where(User.login == login))
    if (not user or user.role == Role.client or not user.is_active
            or not verify_password(user.password_hash, data.password)):
        record_attempt(db, login, ip, False)
        raise HTTPException(401, BAD_CREDENTIALS)
    if user.totp_enabled:
        if not data.totp_code:
            raise HTTPException(401, "totp_required")
        if not pyotp.TOTP(user.totp_secret).verify(data.totp_code.strip(), valid_window=1):
            record_attempt(db, login, ip, False)
            raise HTTPException(401, "Неверный код подтверждения")
    record_attempt(db, login, ip, True)
    open_session(db, response, request, user, Realm.admin)
    return {"ok": True}


@router.post("/admin/logout")
def admin_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    close_session(db, request, response, Realm.admin)
    return {"ok": True}


@router.get("/admin/me")
def admin_me(actor: Actor = Depends(current_staff)):
    return staff_me(actor)


@router.post("/admin/password")
def admin_change_password(data: ChangePasswordIn, actor: Actor = Depends(current_staff),
                          db: Session = Depends(get_db)):
    if not verify_password(actor.user.password_hash, data.current_password):
        raise HTTPException(400, "Текущий пароль указан неверно")
    check_password_strength(data.new_password)
    actor.user.password_hash = hash_password(data.new_password)
    audit.record(db, actor, "user.password_changed", "user", actor.user.id)
    db.commit()
    return {"ok": True}


# --- Второй фактор (TOTP) для сотрудников; для владельца обязателен в production ---

@router.post("/admin/totp/setup")
def totp_setup(actor: Actor = Depends(current_staff), db: Session = Depends(get_db)):
    if actor.user.totp_enabled:
        raise HTTPException(409, "Второй фактор уже включён")
    secret = pyotp.random_base32()
    actor.user.totp_secret = secret
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=actor.user.login, issuer_name="Islamic Car Admin")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/admin/totp/enable")
def totp_enable(data: TotpCodeIn, actor: Actor = Depends(current_staff), db: Session = Depends(get_db)):
    u = actor.user
    if not u.totp_secret or not pyotp.TOTP(u.totp_secret).verify(data.code.strip(), valid_window=1):
        raise HTTPException(400, "Неверный код. Проверьте время на телефоне и попробуйте снова.")
    u.totp_enabled = True
    audit.record(db, actor, "user.totp_enabled", "user", u.id)
    db.commit()
    return {"ok": True}


@router.post("/admin/totp/disable")
def totp_disable(data: TotpCodeIn, actor: Actor = Depends(current_staff), db: Session = Depends(get_db)):
    u = actor.user
    if not u.totp_enabled or not pyotp.TOTP(u.totp_secret).verify(data.code.strip(), valid_window=1):
        raise HTTPException(400, "Неверный код")
    u.totp_enabled = False
    u.totp_secret = None
    audit.record(db, actor, "user.totp_disabled", "user", u.id)
    db.commit()
    return {"ok": True}


# --- Покупатели ---

@router.post("/client/login")
def client_login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        login = normalize_phone(data.login)
    except HTTPException:
        login = data.login.strip().lower()
    ip = client_ip(request)
    ensure_not_throttled(db, login, ip)
    user = db.scalar(select(User).where(User.login == login))
    if (not user or user.role != Role.client or not user.is_active
            or not verify_password(user.password_hash, data.password)):
        record_attempt(db, login, ip, False)
        raise HTTPException(401, BAD_CREDENTIALS)
    record_attempt(db, login, ip, True)
    open_session(db, response, request, user, Realm.client)
    return {"ok": True}


@router.post("/client/logout")
def client_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    close_session(db, request, response, Realm.client)
    return {"ok": True}


@router.get("/client/me")
def client_me(actor: Actor = Depends(current_client)):
    c = actor.user.client
    return {"full_name": c.full_name, "phone": c.phone, "email": c.email, "login": actor.user.login}


@router.post("/client/activate")
def client_activate(data: ActivateIn, db: Session = Depends(get_db)):
    record = db.scalar(select(ActivationToken).where(ActivationToken.token_hash == hash_token(data.token)))
    if not record or record.used_at or as_aware(record.expires_at) <= datetime.now(UTC):
        raise HTTPException(400, "Ссылка недействительна или устарела. Попросите менеджера выдать новую.")
    check_password_strength(data.password)
    user = db.get(User, record.user_id)
    user.password_hash = hash_password(data.password)
    user.is_active = True
    record.used_at = datetime.now(UTC)
    audit.record(db, None, "client.cabinet_activated", "client", user.client_id)
    db.commit()
    return {"ok": True, "login": user.login}
