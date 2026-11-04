"""Очередь задач в PostgreSQL.

Почему не Celery + Redis: задачи живут в той же базе, что и данные, ставятся в той же транзакции,
что и изменение (нет потерь между базой и брокером), переживают перезапуск, не требуют отдельного
сервиса и работают на Windows. Параллельные обработчики не берут одну задачу дважды благодаря
SELECT … FOR UPDATE SKIP LOCKED.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Job, JobStatus

LEASE = timedelta(minutes=10)


def enqueue(db: Session, kind: str, payload: dict, run_at: datetime | None = None,
            dedupe_key: str | None = None, max_attempts: int = 5) -> Job | None:
    """Ставит задачу. С dedupe_key повторная постановка той же задачи игнорируется."""
    if dedupe_key and db.scalar(select(Job.id).where(Job.dedupe_key == dedupe_key)):
        return None
    job = Job(kind=kind, payload=payload, run_at=run_at or datetime.now(UTC), dedupe_key=dedupe_key,
              max_attempts=max_attempts)
    db.add(job)
    db.flush()
    return job


def requeue_stale(db: Session, now: datetime) -> int:
    """Задачи, взятые обработчиком, который упал или был перезапущен, возвращаются в очередь."""
    jobs = db.scalars(select(Job).where(Job.status == JobStatus.running, Job.locked_until < now)
                      .with_for_update(skip_locked=True))
    count = 0
    for job in jobs:
        if db.bind.dialect.name == "postgresql":
            acquired = db.execute(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                                  {"key": str(job.id)}).scalar()
            if not acquired:
                continue
        job.status, job.locked_until = JobStatus.queued, None
        count += 1
    return count


def claim(db: Session, now: datetime, limit: int = 1) -> list[Job]:
    jobs = list(db.scalars(
        select(Job).where(Job.status == JobStatus.queued, Job.run_at <= now)
        .order_by(Job.run_at).limit(limit).with_for_update(skip_locked=True)))
    for job in jobs:
        job.status = JobStatus.running
        job.locked_until = now + LEASE
    db.commit()
    return jobs
