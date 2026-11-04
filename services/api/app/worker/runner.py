"""Фоновый обработчик: периодические задачи, отправка сообщений, контроль сроков, резервные копии."""

import logging
import socket
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import Job, JobStatus, WorkerHeartbeat
from app.services import backups, messaging, online_payments, reminders, staff_tasks
from app.worker.queue import claim, enqueue, requeue_stale

log = logging.getLogger("islamcar.worker")

Handler = Callable[[Session, dict, datetime], object]

HANDLERS: dict[str, Handler] = {
    "plan_reminders": lambda db, payload, now: reminders.plan_reminders(db, now),
    "send_message": lambda db, payload, now: messaging.send_message(db, uuid.UUID(payload["message_id"]), now),
    "staff_scan": lambda db, payload, now: staff_tasks.scan(db, now),
    "backup": lambda db, payload, now: backups.run_backup(db, now),
    "verify_backup": lambda db, payload, now: backups.verify_latest(db, now),
    "agents_daily": lambda db, payload, now: run_all_agents(now),
    "sync_online_payments": lambda db, payload, now: online_payments.sync_pending(db, now),
}

PAYMENTS_SYNC_MINUTES = 10

AGENTS_HOUR = 7


def run_all_agents(now: datetime) -> None:
    from app.agents.base import run_agent
    from app.agents.registry import AGENTS
    for code, agent in AGENTS.items():
        if code != "management":
            run_agent(agent, now)
    run_agent(AGENTS["management"], now)


def schedule_periodic(db: Session, now: datetime) -> None:
    s = get_settings()
    step = max(1, s.reminders_every_minutes)
    bucket = now.replace(minute=(now.minute // step) * step, second=0, microsecond=0)
    enqueue(db, "plan_reminders", {}, now, dedupe_key=f"plan_reminders:{bucket:%Y%m%dT%H%M}")
    enqueue(db, "staff_scan", {}, now, dedupe_key=f"staff_scan:{now:%Y%m%dT%H}")
    if online_payments.get_payment_provider():
        slot = now.replace(minute=(now.minute // PAYMENTS_SYNC_MINUTES) * PAYMENTS_SYNC_MINUTES, second=0,
                           microsecond=0)
        enqueue(db, "sync_online_payments", {}, now, dedupe_key=f"sync_online_payments:{slot:%Y%m%dT%H%M}")
    local_now = now.astimezone(ZoneInfo(s.company_timezone))
    agents_at = local_now.replace(hour=AGENTS_HOUR, minute=0, second=0, microsecond=0)
    enqueue(db, "agents_daily", {}, max(agents_at.astimezone(UTC), now), dedupe_key=f"agents_daily:{local_now:%Y%m%d}")
    if s.backup_dir:
        local = now.astimezone(ZoneInfo(s.company_timezone))
        at = local.replace(hour=s.backup_hour, minute=0, second=0, microsecond=0)
        enqueue(db, "backup", {}, max(at.astimezone(UTC), now), dedupe_key=f"backup:{local:%Y%m%d}")
        year, week, _ = local.isocalendar()
        enqueue(db, "verify_backup", {}, max((at + timedelta(hours=1)).astimezone(UTC), now),
                dedupe_key=f"verify_backup:{year}W{week}")
    db.commit()


def run_job(job_id: uuid.UUID, now: datetime) -> bool:
    if engine.dialect.name != "postgresql":
        return _run_job(job_id, now)
    with engine.connect() as lock:
        params = {"key": str(job_id)}
        acquired = lock.execute(text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), params).scalar()
        lock.commit()
        if not acquired:
            return False
        try:
            return _run_job(job_id, now)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), params)
            lock.commit()


def _run_job(job_id: uuid.UUID, now: datetime) -> bool:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or job.status != JobStatus.running:
            return False
        handler = HANDLERS.get(job.kind)
        try:
            if handler is None:
                raise ValueError(f"Неизвестный тип задачи: {job.kind}")
            handler(db, job.payload, now)
            job.status = JobStatus.done
            job.finished_at = datetime.now(UTC)
            job.locked_until = None
            db.commit()
            return True
        except Exception:  # noqa: BLE001 — любая ошибка задачи фиксируется и повторяется позже
            db.rollback()
            job = db.get(Job, job_id)
            job.attempts += 1
            job.last_error = traceback.format_exc()[-4000:]
            job.locked_until = None
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.failed
                job.finished_at = datetime.now(UTC)
            else:
                job.status = JobStatus.queued
                job.run_at = now + timedelta(minutes=2 ** job.attempts)
            db.commit()
            log.exception("Задача %s (%s) завершилась ошибкой", job.kind, job.id)
            return False


def run_once(now: datetime | None = None, worker_id: str = "worker", periodic: bool = True) -> int:
    """Один проход: плановые задачи + все задачи, срок которых наступил. Возвращает число выполненных."""
    now = now or datetime.now(UTC)
    done = 0
    for _ in range(20):  # задачи могут порождать новые (план → отправка) — обрабатываем их в том же проходе
        with SessionLocal() as db:
            if periodic and done == 0:
                schedule_periodic(db, now)
            requeue_stale(db, now)
            db.commit()
            jobs = claim(db, now)
        if not jobs:
            break
        for job in jobs:
            done += run_job(job.id, now)
    with SessionLocal() as db:
        hb = db.get(WorkerHeartbeat, worker_id) or WorkerHeartbeat(worker_id=worker_id, jobs_done=0)
        hb.last_seen = datetime.now(UTC)
        hb.jobs_done = (hb.jobs_done or 0) + done
        db.add(hb)
        db.commit()
    return done


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker_id = f"{socket.gethostname()}"
    interval = get_settings().worker_poll_seconds
    log.info("Фоновый обработчик Islamic Car запущен (%s)", worker_id)
    while True:
        try:
            run_once(worker_id=worker_id)
        except Exception:  # noqa: BLE001 — сбой базы не должен останавливать обработчик
            log.exception("Ошибка прохода обработчика")
        time.sleep(interval)
