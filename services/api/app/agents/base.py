"""Каркас агентов: строго ограниченные полномочия, журнал действий, ссылки на основания.

Агент читает данные через отдельную сессию, которая в конце откатывается, — изменить договор, платёж или
статус он не может даже по ошибке. Единственные доступные действия — те, что выданы ему в permissions,
и выполняются они через контекст в отдельной транзакции с записью в журнал запуска.

Агенты версии 3 работают по проверяемым правилам без языковой модели: суммы, сроки и нормы берутся только
из данных системы и библиотек знаний.
"""

import traceback
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import AgentRun
from app.services.notify import notify_staff
from app.services.staff_tasks import open_task


@dataclass
class Finding:
    severity: str  # info | warning | critical
    title: str
    message: str = ""
    link: str = ""
    refs: list[str] = field(default_factory=list)  # коды норм библиотек знаний
    suggestion: str = ""


class PermissionDenied(Exception):
    pass


class AgentContext:
    def __init__(self, agent: "Agent", now: datetime) -> None:
        self.agent = agent
        self.now = now
        self.today: date = now.astimezone(ZoneInfo(get_settings().company_timezone)).date()
        self.actions: list[dict] = []

    def _require(self, permission: str) -> None:
        if permission not in self.agent.permissions:
            raise PermissionDenied(f"Агенту «{self.agent.code}» не разрешено действие {permission}")

    def create_task(self, kind: str, title: str, description: str, link: str, dedupe_key: str,
                    due: date | None = None) -> None:
        self._require("create:tasks")
        with SessionLocal() as db:
            task = open_task(db, f"agent_{kind}", title, description, link, f"agent:{dedupe_key}", due=due)
            db.commit()
        self.actions.append({"action": "create_task", "title": title, "created": task is not None,
                             "dedupe_key": dedupe_key})

    def notify_staff(self, kind: str, title: str, body: str, link: str = "") -> None:
        self._require("create:staff_notifications")
        with SessionLocal() as db:
            notify_staff(db, f"agent.{kind}", title, body, link)
            db.commit()
        self.actions.append({"action": "notify_staff", "title": title})


class Agent:
    code = ""
    title = ""
    description = ""
    permissions: list[str] = []
    reads: list[str] = []

    def run(self, db: Session, ctx: AgentContext) -> list[Finding]:
        raise NotImplementedError


def run_agent(agent: Agent, now: datetime | None = None, user_id=None) -> AgentRun:
    now = now or datetime.now(UTC)
    with SessionLocal() as db:
        run = AgentRun(agent_code=agent.code, status="running", triggered_by=user_id, started_at=now)
        db.add(run)
        db.commit()
        run_id = run.id
    ctx = AgentContext(agent, now)
    reader = SessionLocal()
    try:
        findings = agent.run(reader, ctx)
        status, error = "ok", ""
    except Exception:  # noqa: BLE001 — ошибка агента фиксируется в журнале запуска
        findings, status, error = [], "failed", traceback.format_exc()[-3000:]
    finally:
        reader.rollback()  # агент не может ничего изменить через сессию чтения
        reader.close()
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        run.status = status
        run.error = error
        run.findings = [asdict(f) for f in findings]
        run.actions = ctx.actions
        run.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        return run
