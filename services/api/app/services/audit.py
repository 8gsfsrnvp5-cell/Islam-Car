from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.security import Actor


def record(db: Session, actor: Actor | None, action: str, entity_type: str,
           entity_id: object | None = None, **data: Any) -> None:
    """Добавляет запись в журнал. Коммит выполняет вызывающий код вместе с основным изменением."""
    db.add(AuditLog(
        actor_user_id=actor.user.id if actor else None,
        actor_role=actor.role.value if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        data=_jsonable(data),
        ip=actor.ip if actor else None,
    ))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
