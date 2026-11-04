"""Уведомления (правила, политика, журнал), согласия, залоги, страхование, задачи, резервные копии."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    BackupRun,
    Car,
    Channel,
    Client,
    Consent,
    Contract,
    InsurancePolicy,
    Job,
    JobStatus,
    MessageStatus,
    NotificationEvent,
    NotificationRule,
    OutboundMessage,
    Pledge,
    PledgeStatus,
    StaffTask,
    TaskStatus,
    WorkerHeartbeat,
)
from app.schemas import (
    ConsentIn,
    ContactVerifyIn,
    InsuranceIn,
    PledgeIn,
    PolicyIn,
    RulesIn,
    TaskDoneIn,
    TaskIn,
)
from app.security import Actor, require
from app.services import audit, messaging
from app.services.contracts import get_company
from app.services.providers import channel_status
from app.services.staff_tasks import close_task, open_task
from app.worker.queue import enqueue

router = APIRouter(prefix="/api/admin", tags=["admin: operations"])

# Допустимые переходы статусов залога — отражают реальные шаги, которые выполняет сотрудник
PLEDGE_FLOW = {
    PledgeStatus.planned: {PledgeStatus.documents_prepared, PledgeStatus.submitted, PledgeStatus.not_required},
    PledgeStatus.documents_prepared: {PledgeStatus.submitted, PledgeStatus.planned, PledgeStatus.not_required},
    PledgeStatus.submitted: {PledgeStatus.registered, PledgeStatus.documents_prepared},
    PledgeStatus.registered: {PledgeStatus.release_required},
    PledgeStatus.release_required: {PledgeStatus.release_submitted},
    PledgeStatus.release_submitted: {PledgeStatus.released, PledgeStatus.release_required},
    PledgeStatus.released: set(),
    PledgeStatus.not_required: {PledgeStatus.planned},
}


# --- Правила, политика, каналы ----------------------------------------------------------

def rule_dict(r: NotificationRule) -> dict:
    return {"id": r.id, "event": r.event, "offset_days": r.offset_days, "channels": r.channels, "enabled": r.enabled}


@router.get("/notification-settings")
def notification_settings(actor: Actor = Depends(require("notifications.read")), db: Session = Depends(get_db)):
    rules = sorted(messaging.ensure_default_rules(db), key=lambda r: (r.event.value, r.offset_days))
    db.commit()
    return {"rules": [rule_dict(r) for r in rules], "policy": messaging.get_policy(db), "channels": channel_status()}


@router.put("/notification-settings/rules")
def save_rules(data: RulesIn, actor: Actor = Depends(require("settings.write")), db: Session = Depends(get_db)):
    existing = {r.id: r for r in messaging.ensure_default_rules(db)}
    seen = set()
    for item in data.rules:
        channels = [c for c in item.channels if c in {ch.value for ch in Channel}]
        rule = existing.get(item.id) if item.id else None
        if rule is None:
            rule = NotificationRule(event=NotificationEvent(item.event), offset_days=item.offset_days)
            db.add(rule)
        rule.event = NotificationEvent(item.event)
        rule.offset_days = 0 if item.event in ("due_day", "payment_confirmed") else item.offset_days
        rule.channels = channels
        rule.enabled = item.enabled
        key = (rule.event, rule.offset_days)
        if key in seen:
            raise HTTPException(422, "Два правила с одинаковым событием и сроком")
        seen.add(key)
    for rid, rule in existing.items():
        if rid not in {i.id for i in data.rules}:
            db.delete(rule)
    audit.record(db, actor, "notifications.rules_updated", "settings", "rules",
                 rules=[i.model_dump(mode="json") for i in data.rules])
    db.commit()
    return notification_settings(actor, db)


@router.put("/notification-settings/policy")
def save_policy(data: PolicyIn, actor: Actor = Depends(require("settings.write")), db: Session = Depends(get_db)):
    co = get_company(db)
    policy = data.model_dump(mode="json")
    co.communication_policy = policy
    audit.record(db, actor, "notifications.policy_updated", "settings", "policy", policy=policy)
    db.commit()
    return notification_settings(actor, db)


# --- Журнал сообщений и состояние обработчика ---------------------------------------------

def message_dict(m: OutboundMessage, client_name: str | None = None, number: str | None = None) -> dict:
    return {"id": m.id, "client_id": m.client_id, "client": client_name, "contract_id": m.contract_id,
            "contract_number": number, "channel": m.channel, "purpose": m.purpose, "body": m.body,
            "address_masked": m.address_masked, "status": m.status, "status_reason": m.status_reason,
            "scheduled_for": m.scheduled_for, "sent_at": m.sent_at, "attempts": m.attempts, "provider": m.provider,
            "created_at": m.created_at}


@router.get("/messages")
def messages(status: MessageStatus | None = None, channel: Channel | None = None, client_id: uuid.UUID | None = None,
             contract_id: uuid.UUID | None = None, actor: Actor = Depends(require("notifications.read")),
             db: Session = Depends(get_db)):
    stmt = (select(OutboundMessage, Client.full_name, Contract.number)
            .join(Client, Client.id == OutboundMessage.client_id)
            .outerjoin(Contract, Contract.id == OutboundMessage.contract_id)
            .order_by(OutboundMessage.created_at.desc()).limit(500))
    if status:
        stmt = stmt.where(OutboundMessage.status == status)
    if channel:
        stmt = stmt.where(OutboundMessage.channel == channel)
    if client_id:
        stmt = stmt.where(OutboundMessage.client_id == client_id)
    if contract_id:
        stmt = stmt.where(OutboundMessage.contract_id == contract_id)
    return {"items": [message_dict(m, name, number) for m, name, number in db.execute(stmt).all()],
            "counts": messaging.message_counts(db)}


@router.post("/messages/{message_id}/cancel")
def cancel_message(message_id: uuid.UUID, actor: Actor = Depends(require("settings.write")),
                   db: Session = Depends(get_db)):
    m = db.get(OutboundMessage, message_id)
    if not m or m.status != MessageStatus.scheduled:
        raise HTTPException(409, "Отменить можно только запланированное сообщение")
    m.status = MessageStatus.cancelled
    m.status_reason = "Отменено сотрудником"
    audit.record(db, actor, "message.cancelled", "message", m.id)
    db.commit()
    return message_dict(m)


@router.get("/worker")
def worker_status(actor: Actor = Depends(require("notifications.read")), db: Session = Depends(get_db)):
    beats = db.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen.desc())).all()
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    failed = db.scalars(select(Job).where(Job.status == JobStatus.failed).order_by(Job.finished_at.desc()).limit(10))
    now = datetime.now(UTC)
    last = beats[0].last_seen if beats else None
    if last and not last.tzinfo:
        last = last.replace(tzinfo=UTC)
    return {"alive": bool(last and now - last < timedelta(minutes=2)), "last_seen": last,
            "workers": [{"worker_id": b.worker_id, "last_seen": b.last_seen, "jobs_done": b.jobs_done} for b in beats],
            "jobs": {s.value: counts.get(s, 0) for s in JobStatus},
            "failed": [{"id": j.id, "kind": j.kind, "attempts": j.attempts, "error": j.last_error[-500:],
                        "finished_at": j.finished_at} for j in failed]}


# --- Согласия и подтверждение контактов ------------------------------------------------------

@router.get("/clients/{client_id}/communications")
def client_communications(client_id: uuid.UUID, actor: Actor = Depends(require("clients.read")),
                          db: Session = Depends(get_db)):
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(404, "Клиент не найден")
    history = db.scalars(select(Consent).where(Consent.client_id == client_id).order_by(Consent.recorded_at.desc()))
    return {"phone_verified": c.phone_verified, "email_verified": c.email_verified, "email": c.email,
            "consents": messaging.current_consents(db, client_id),
            "history": [{"channel": h.channel, "granted": h.granted, "source": h.source, "recorded_at": h.recorded_at}
                        for h in history]}


@router.post("/clients/{client_id}/consents")
def record_consent(client_id: uuid.UUID, data: ConsentIn, actor: Actor = Depends(require("clients.write")),
                   db: Session = Depends(get_db)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "Клиент не найден")
    db.add(Consent(client_id=client_id, channel=Channel(data.channel), granted=data.granted, source=data.source,
                   recorded_by=actor.user.id))
    audit.record(db, actor, "client.consent", "client", client_id, channel=data.channel, granted=data.granted,
                 source=data.source)
    db.commit()
    return client_communications(client_id, actor, db)


@router.post("/clients/{client_id}/contacts/verify")
def verify_contact(client_id: uuid.UUID, data: ContactVerifyIn, actor: Actor = Depends(require("clients.verify")),
                   db: Session = Depends(get_db)):
    """Сотрудник подтверждает, что телефон или e-mail принадлежит клиенту (например, по ответу на звонок)."""
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(404, "Клиент не найден")
    if data.contact == "email" and data.verified and not c.email:
        raise HTTPException(422, "У клиента не указан e-mail")
    setattr(c, f"{data.contact}_verified", data.verified)
    audit.record(db, actor, "client.contact_verified", "client", client_id, contact=data.contact,
                 verified=data.verified)
    db.commit()
    return client_communications(client_id, actor, db)


# --- Залоги ---------------------------------------------------------------------------

def pledge_dict(p: Pledge) -> dict:
    c = p.contract
    return {"id": p.id, "contract_id": p.contract_id, "contract_number": c.number, "contract_status": c.status,
            "client": c.client.full_name, "car": f"{c.car.make} {c.car.model}", "vin": c.car.vin, "status": p.status,
            "registry_number": p.registry_number, "registered_on": p.registered_on, "notary": p.notary,
            "release_number": p.release_number, "released_on": p.released_on, "notes": p.notes,
            "updated_at": p.updated_at, "allowed_next": sorted(s.value for s in PLEDGE_FLOW[p.status])}


@router.get("/pledges")
def list_pledges(actor: Actor = Depends(require("contracts.read")), db: Session = Depends(get_db)):
    return [pledge_dict(p) for p in db.scalars(select(Pledge).order_by(Pledge.updated_at.desc()))]


@router.get("/contracts/{contract_id}/pledge")
def get_pledge(contract_id: uuid.UUID, actor: Actor = Depends(require("contracts.read")),
               db: Session = Depends(get_db)):
    p = db.scalar(select(Pledge).where(Pledge.contract_id == contract_id))
    return pledge_dict(p) if p else None


@router.put("/contracts/{contract_id}/pledge")
def update_pledge(contract_id: uuid.UUID, data: PledgeIn, actor: Actor = Depends(require("contracts.write")),
                  db: Session = Depends(get_db)):
    contract = db.get(Contract, contract_id)
    if not contract or contract.number is None:
        raise HTTPException(404, "Договор не найден или не подписан")
    p = db.scalar(select(Pledge).where(Pledge.contract_id == contract_id))
    if p is None:
        p = Pledge(contract_id=contract_id, status=PledgeStatus.planned)
        db.add(p)
        db.flush()
    new = PledgeStatus(data.status)
    if new != p.status and new not in PLEDGE_FLOW[p.status]:
        raise HTTPException(409, f"Из статуса «{p.status.value}» нельзя перейти в «{new.value}»")
    if new == PledgeStatus.registered and not (data.registry_number.strip() and data.registered_on):
        raise HTTPException(422, "Статус «зарегистрирован» — только с номером уведомления и датой из реестра")
    if new == PledgeStatus.released and not (data.release_number.strip() and data.released_on):
        raise HTTPException(422, "Статус «прекращён» — только с номером уведомления об исключении и датой")
    if new == PledgeStatus.release_required and contract.status.value != "completed":
        raise HTTPException(409, "Прекращение залога — после полной оплаты договора")
    before = p.status
    for field in ("registry_number", "registered_on", "notary", "release_number", "released_on", "notes"):
        setattr(p, field, getattr(data, field))
    p.status = new
    p.updated_by = actor.user.id
    audit.record(db, actor, "pledge.updated", "pledge", p.id, contract=contract.number, before=before, after=new,
                 registry_number=data.registry_number or None)
    db.commit()
    return pledge_dict(p)


# --- Страхование -----------------------------------------------------------------------

def insurance_dict(i: InsurancePolicy) -> dict:
    return {"id": i.id, "car_id": i.car_id, "car": f"{i.car.make} {i.car.model}", "vin": i.car.vin,
            "contract_id": i.contract_id, "kind": i.kind, "number": i.number, "insurer": i.insurer,
            "valid_from": i.valid_from, "valid_to": i.valid_to, "required_by_contract": i.required_by_contract,
            "notes": i.notes}


@router.get("/insurance")
def list_insurance(contract_id: uuid.UUID | None = None, actor: Actor = Depends(require("contracts.read")),
                   db: Session = Depends(get_db)):
    stmt = select(InsurancePolicy).order_by(InsurancePolicy.valid_to)
    if contract_id:
        stmt = stmt.where(InsurancePolicy.contract_id == contract_id)
    return [insurance_dict(i) for i in db.scalars(stmt)]


@router.post("/insurance", status_code=201)
def add_insurance(data: InsuranceIn, actor: Actor = Depends(require("contracts.write")), db: Session = Depends(get_db)):
    if not db.get(Car, data.car_id):
        raise HTTPException(404, "Автомобиль не найден")
    if data.valid_to <= data.valid_from:
        raise HTTPException(422, "Дата окончания должна быть позже даты начала")
    policy = InsurancePolicy(**data.model_dump(), created_by=actor.user.id)
    db.add(policy)
    db.flush()
    audit.record(db, actor, "insurance.added", "insurance", policy.id, kind=data.kind, valid_to=data.valid_to)
    db.commit()
    db.refresh(policy)
    return insurance_dict(policy)


# --- Задачи ------------------------------------------------------------------------------

def task_dict(t: StaffTask) -> dict:
    return {"id": t.id, "kind": t.kind, "title": t.title, "description": t.description, "due_date": t.due_date,
            "status": t.status, "link": t.link, "created_at": t.created_at, "done_at": t.done_at,
            "result_note": t.result_note, "automatic": t.created_by is None}


@router.get("/tasks")
def list_tasks(status: TaskStatus | None = TaskStatus.open, actor: Actor = Depends(require("dashboard.read")),
               db: Session = Depends(get_db)):
    stmt = select(StaffTask).order_by(StaffTask.due_date.is_(None), StaffTask.due_date, StaffTask.created_at.desc())
    if status:
        stmt = stmt.where(StaffTask.status == status)
    return [task_dict(t) for t in db.scalars(stmt.limit(500))]


@router.post("/tasks", status_code=201)
def create_task(data: TaskIn, actor: Actor = Depends(require("dashboard.read")), db: Session = Depends(get_db)):
    t = open_task(db, "manual", data.title, data.description, data.link, None, due=data.due_date,
                  created_by=actor.user.id)
    db.commit()
    return task_dict(t)


@router.post("/tasks/{task_id}/done")
def complete_task(task_id: uuid.UUID, data: TaskDoneIn, actor: Actor = Depends(require("dashboard.read")),
                  db: Session = Depends(get_db)):
    t = db.get(StaffTask, task_id)
    if not t or t.status != TaskStatus.open:
        raise HTTPException(409, "Задача не найдена или уже закрыта")
    close_task(t, actor.user.id, data.note, datetime.now(UTC))
    audit.record(db, actor, "task.done", "task", t.id, note=data.note)
    db.commit()
    return task_dict(t)


# --- Резервные копии ---------------------------------------------------------------------

@router.get("/backups")
def list_backups(actor: Actor = Depends(require("users.manage")), db: Session = Depends(get_db)):
    from app.config import get_settings
    s = get_settings()
    runs = db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(50)).all()
    return {"configured": bool(s.backup_dir) and s.database_url.startswith("postgresql"),
            "retention_days": s.backup_retention_days, "backup_hour": s.backup_hour,
            "full_restore_check": bool(s.backup_verify_database_url),
            "runs": [{"id": r.id, "kind": r.kind, "status": r.status, "file_name": r.file_name,
                      "size_bytes": r.size_bytes, "sha256": r.sha256, "detail": r.detail, "started_at": r.started_at,
                      "finished_at": r.finished_at} for r in runs]}


@router.post("/backups/{kind}")
def queue_backup(kind: str, actor: Actor = Depends(require("users.manage")), db: Session = Depends(get_db)):
    if kind not in ("backup", "verify_backup"):
        raise HTTPException(404, "Неизвестное действие")
    enqueue(db, kind, {}, dedupe_key=f"{kind}:manual:{uuid.uuid4().hex}", max_attempts=1)
    audit.record(db, actor, f"{kind}.requested", "backup", None)
    db.commit()
    return {"queued": True, "message": "Задача поставлена в очередь фонового обработчика"}
