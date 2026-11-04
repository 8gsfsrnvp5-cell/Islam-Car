import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import LoginAttempt, Realm, Role, Session_, User
from app.permissions import has_permission

COOKIE_NAMES = {Realm.admin: "ic_admin_session", Realm.client: "ic_client_session"}
MIN_PASSWORD_LENGTH = 10

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def check_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(422, f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def client_ip(request: Request) -> str | None:
    # Only the ASGI server may resolve headers from explicitly trusted proxies.
    return request.client.host if request.client else None


def as_aware(dt: datetime) -> datetime:
    # SQLite в тестах возвращает naive datetime; в PostgreSQL — timezone-aware
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --- Защита от перебора паролей ---------------------------------------------

def ensure_not_throttled(db: Session, login: str, ip: str | None) -> None:
    s = get_settings()
    since = datetime.now(UTC) - timedelta(minutes=s.login_window_minutes)
    failures = db.scalar(
        select(func.count()).select_from(LoginAttempt)
        .where(LoginAttempt.login == login, LoginAttempt.success.is_(False), LoginAttempt.created_at >= since))
    ip_failures = 0
    if ip:
        ip_failures = db.scalar(
            select(func.count()).select_from(LoginAttempt)
            .where(LoginAttempt.ip == ip, LoginAttempt.success.is_(False), LoginAttempt.created_at >= since))
    if failures >= s.login_max_failures or ip_failures >= s.login_max_failures * 4:
        raise HTTPException(
            429, f"Слишком много неудачных попыток входа. Повторите через {s.login_window_minutes} минут.")


def record_attempt(db: Session, login: str, ip: str | None, success: bool) -> None:
    db.add(LoginAttempt(login=login, ip=ip, success=success))
    db.commit()


# --- Сессии ------------------------------------------------------------------

def open_session(db: Session, response: Response, request: Request, user: User, realm: Realm) -> None:
    s = get_settings()
    hours = s.admin_session_hours if realm == Realm.admin else s.client_session_hours
    token = new_token()
    db.add(Session_(
        token_hash=hash_token(token), user_id=user.id, realm=realm,
        expires_at=datetime.now(UTC) + timedelta(hours=hours),
        ip=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:300],
    ))
    user.last_login_at = datetime.now(UTC)
    db.commit()
    response.set_cookie(
        COOKIE_NAMES[realm], token, max_age=hours * 3600, httponly=True,
        secure=s.cookie_secure, samesite="lax", path="/",
    )


def consume_totp(db: Session, user: User, code: str) -> bool:
    if not user.totp_secret:
        return False
    totp = pyotp.TOTP(user.totp_secret)
    step = int(time.time()) // totp.interval
    matched = next((s for s in (step, step - 1, step + 1)
                    if secrets.compare_digest(totp.at(s * totp.interval), code.strip())), None)
    if matched is None:
        return False
    result = db.execute(update(User).where(
        User.id == user.id, User.totp_secret == user.totp_secret,
        (User.totp_last_step.is_(None)) | (User.totp_last_step < matched),
    ).values(totp_last_step=matched))
    return result.rowcount == 1


def revoke_sessions(db: Session, user_id, keep_id=None) -> None:
    stmt = update(Session_).where(Session_.user_id == user_id, Session_.revoked_at.is_(None))
    if keep_id is not None:
        stmt = stmt.where(Session_.id != keep_id)
    db.execute(stmt.values(revoked_at=datetime.now(UTC)))


def close_session(db: Session, request: Request, response: Response, realm: Realm) -> None:
    token = request.cookies.get(COOKIE_NAMES[realm])
    if token:
        sess = db.scalar(select(Session_).where(Session_.token_hash == hash_token(token)))
        if sess and not sess.revoked_at:
            sess.revoked_at = datetime.now(UTC)
            db.commit()
    response.delete_cookie(COOKIE_NAMES[realm], path="/")


@dataclass
class Actor:
    user: User
    session: Session_
    ip: str | None

    @property
    def role(self) -> Role:
        return self.user.role

    def can(self, permission: str) -> bool:
        return has_permission(self.user.role, permission)


def _load_actor(request: Request, db: Session, realm: Realm) -> Actor:
    token = request.cookies.get(COOKIE_NAMES[realm])
    if not token:
        raise HTTPException(401, "Требуется вход")
    sess = db.scalar(select(Session_).where(Session_.token_hash == hash_token(token)))
    now = datetime.now(UTC)
    if not sess or sess.realm != realm or sess.revoked_at or as_aware(sess.expires_at) <= now:
        raise HTTPException(401, "Сессия истекла, войдите снова")
    user = sess.user
    if not user.is_active:
        raise HTTPException(401, "Учётная запись отключена")
    if realm == Realm.admin and user.role == Role.client:
        raise HTTPException(403, "Нет доступа")
    if realm == Realm.client and (user.role != Role.client or user.client_id is None):
        raise HTTPException(403, "Нет доступа")
    if (realm == Realm.admin and user.role == Role.owner and not user.totp_enabled
            and get_settings().owner_2fa_required and request.url.path not in OWNER_PATHS_WITHOUT_2FA):
        # Владелец без второго фактора может только включить его
        raise HTTPException(403, "owner_2fa_required")
    return Actor(user=user, session=sess, ip=client_ip(request))


OWNER_PATHS_WITHOUT_2FA = {
    "/api/auth/admin/me", "/api/auth/admin/logout", "/api/auth/admin/password",
    "/api/auth/admin/totp/setup", "/api/auth/admin/totp/enable",
}


def current_staff(request: Request, db: Session = Depends(get_db)) -> Actor:
    return _load_actor(request, db, Realm.admin)


def current_client(request: Request, db: Session = Depends(get_db)) -> Actor:
    return _load_actor(request, db, Realm.client)


def require(permission: str):
    def dependency(actor: Actor = Depends(current_staff)) -> Actor:
        if not actor.can(permission):
            raise HTTPException(403, "Недостаточно прав для этого действия")
        return actor
    return dependency
