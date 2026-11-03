"""Помощник по библиотекам знаний: статус, включение владельцем, вопросы сотрудников."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog
from app.schemas import StrictModel
from app.security import Actor, current_staff, require
from app.services import assistant, audit
from app.services.common import today
from app.services.contracts import get_company

router = APIRouter(prefix="/api/admin/assistant", tags=["admin: assistant"])

MAX_QUESTIONS_PER_HOUR = 30
CONFIRMATION = ("Во внешний сервис (Claude API, Anthropic) передаются только записи библиотек знаний и вопрос "
                "сотрудника без персональных данных. Данные клиентов, договоров и платежей не передаются.")


class AssistantSettingsIn(StrictModel):
    enabled: bool
    confirm_data_scope: bool = False


class QuestionIn(StrictModel):
    question: str = Field(min_length=5, max_length=assistant.MAX_QUESTION)


def status_dict(db: Session, actor: Actor) -> dict:
    st = assistant.status(db)
    policy = get_company(db).assistant_policy or {}
    return {"enabled": st.enabled, "configured": st.configured, "model": st.model, "reason": st.reason,
            "can_use": actor.can("assistant.use"), "can_manage": actor.can("settings.write"),
            "changed_at": policy.get("changed_at"), "data_scope": CONFIRMATION, "disclaimer": assistant.DISCLAIMER}


@router.get("")
def get_status(actor: Actor = Depends(current_staff), db: Session = Depends(get_db)):
    return status_dict(db, actor)


@router.put("/settings")
def update_settings(data: AssistantSettingsIn, actor: Actor = Depends(require("settings.write")),
                    db: Session = Depends(get_db)):
    """Включает или выключает помощника. Включение — только с подтверждением состава передаваемых данных."""
    if data.enabled and not data.confirm_data_scope:
        raise HTTPException(422, "Подтвердите, какие данные передаются во внешний сервис")
    co = get_company(db)
    # Прочие ключи политики (например, распознавание фото автомобилей) сохраняются
    co.assistant_policy = {**(co.assistant_policy or {}), "enabled": data.enabled,
                           "changed_at": datetime.now(UTC).isoformat(), "changed_by": str(actor.user.id)}
    audit.record(db, actor, "assistant.enabled" if data.enabled else "assistant.disabled", "settings", 1,
                 data_scope=CONFIRMATION if data.enabled else None)
    db.commit()
    return status_dict(db, actor)


@router.post("/ask")
def ask(data: QuestionIn, actor: Actor = Depends(require("assistant.use")), db: Session = Depends(get_db)):
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    recent = db.scalar(select(func.count(AuditLog.id)).where(
        AuditLog.actor_user_id == actor.user.id, AuditLog.action == "assistant.asked",
        AuditLog.created_at >= hour_ago)) or 0
    if recent >= MAX_QUESTIONS_PER_HOUR:
        raise HTTPException(429, "Слишком много вопросов за час — попробуйте позже")
    result = assistant.ask(db, data.question, today())
    # В журнал — только вопрос без персональных данных и ссылки; ответ не хранится
    audit.record(db, actor, "assistant.asked", "assistant", None, question=result["question_sent"],
                 removed=result["removed"], cited=[s["code"] for s in result["sources"]], verdict=result["verdict"])
    db.commit()
    return result
