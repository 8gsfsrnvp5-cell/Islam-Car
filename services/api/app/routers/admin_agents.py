"""Центр агентов: реестр, полномочия, запуск, журнал запусков с выводами и действиями."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import run_agent
from app.agents.registry import AGENTS
from app.db import get_db
from app.models import AgentRun
from app.security import Actor, require
from app.services import audit

router = APIRouter(prefix="/api/admin/agents", tags=["admin: agents"])


def run_dict(r: AgentRun, full: bool = False) -> dict:
    counts = {s: sum(1 for f in r.findings if f["severity"] == s) for s in ("critical", "warning", "info")}
    data = {"id": r.id, "agent_code": r.agent_code, "status": r.status, "started_at": r.started_at,
            "finished_at": r.finished_at, "counts": counts, "actions_count": len(r.actions),
            "manual": r.triggered_by is not None}
    if full:
        data.update(findings=r.findings, actions=r.actions, error=r.error)
    return data


@router.get("")
def list_agents(actor: Actor = Depends(require("agents.read")), db: Session = Depends(get_db)):
    result = []
    for code, agent in AGENTS.items():
        last = db.scalar(select(AgentRun).where(AgentRun.agent_code == code)
                         .order_by(AgentRun.started_at.desc()).limit(1))
        result.append({"code": code, "title": agent.title, "description": agent.description,
                       "permissions": agent.permissions, "reads": agent.reads,
                       "last_run": run_dict(last, full=True) if last else None})
    return {"agents": result, "mode": "Проверяемые правила без языковой модели",
            "principles": ["Суммы, сроки и нормы — только из данных системы и библиотек знаний",
                           "Агент не меняет договоры, платежи и статусы: чтение в отдельной сессии с откатом",
                           "Разрешённые действия — только задачи сотрудникам и внутренние уведомления, с журналом",
                           "Персональные данные не передаются внешним ИИ-сервисам"]}


@router.post("/{code}/run")
def run_now(code: str, actor: Actor = Depends(require("agents.run")), db: Session = Depends(get_db)):
    agent = AGENTS.get(code)
    if not agent:
        raise HTTPException(404, "Агент не найден")
    run = run_agent(agent, user_id=actor.user.id)
    audit.record(db, actor, "agent.run", "agent", code, run=run.id, status=run.status)
    db.commit()
    return run_dict(run, full=True)


@router.get("/runs")
def runs(code: str | None = None, actor: Actor = Depends(require("agents.read")), db: Session = Depends(get_db)):
    stmt = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(100)
    if code:
        stmt = stmt.where(AgentRun.agent_code == code)
    return [run_dict(r) for r in db.scalars(stmt)]


@router.get("/runs/{run_id}")
def run_detail(run_id: uuid.UUID, actor: Actor = Depends(require("agents.read")), db: Session = Depends(get_db)):
    r = db.get(AgentRun, run_id)
    if not r:
        raise HTTPException(404, "Запуск не найден")
    return run_dict(r, full=True)
