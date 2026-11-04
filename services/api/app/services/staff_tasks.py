"""Задачи сотрудникам и фоновый контроль сроков.

Система только напоминает и готовит работу: юридические меры сама не применяет.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Document,
    DocumentStatus,
    InsurancePolicy,
    Job,
    JobStatus,
    Pledge,
    PledgeStatus,
    StaffTask,
    TaskStatus,
    TaxCalendarEvent,
)
from app.services.dashboard import live_ledgers
from app.services.notify import notify_staff

OVERDUE_CONTACT_DAYS = 3
OVERDUE_ESCALATION_DAYS = 30
PLEDGE_SETUP_DAYS = 7
INSURANCE_WARN_DAYS = 30


def open_task(db: Session, kind: str, title: str, description: str, link: str, dedupe_key: str | None,
              due: date | None = None, created_by=None) -> StaffTask | None:
    """Создаёт задачу, если задачи с тем же ключом ещё не было."""
    if dedupe_key and db.scalar(select(StaffTask.id).where(StaffTask.dedupe_key == dedupe_key)):
        return None
    task = StaffTask(kind=kind, title=title, description=description, link=link, dedupe_key=dedupe_key,
                     due_date=due, created_by=created_by)
    db.add(task)
    db.flush()
    return task


def scan(db: Session, now: datetime) -> int:
    today = now.astimezone(ZoneInfo(get_settings().company_timezone)).date()
    created = 0

    for c, lg in live_ledgers(db, today):
        if not lg.oldest_overdue_date:
            continue
        days = (today - lg.oldest_overdue_date).days
        link = f"/contracts/{c.id}"
        if days >= OVERDUE_CONTACT_DAYS and open_task(
                db, "overdue_contact", f"Связаться с покупателем: просрочка по договору № {c.number}",
                f"{c.client.full_name}. Просрочено {days} дн. Уточнить причину, предложить решение. "
                f"Проценты и штрафы не начисляются.", link,
                f"overdue_contact:{c.id}:{lg.oldest_overdue_date}", due=today):
            created += 1
        if days >= OVERDUE_ESCALATION_DAYS and open_task(
                db, "overdue_escalation", f"Подготовить материалы по просрочке: договор № {c.number}",
                "Подготовить уведомление о просрочке и акт сверки для решения ответственного лица или юриста. "
                "Санкции автоматически не применяются.", link,
                f"overdue_escalation:{c.id}:{lg.oldest_overdue_date}", due=today + timedelta(days=3)):
            created += 1

    for p in db.scalars(select(Pledge).where(Pledge.status.in_([PledgeStatus.planned, PledgeStatus.release_required]))):
        link = f"/contracts/{p.contract_id}"
        if p.status == PledgeStatus.release_required:
            if open_task(db, "pledge_release", f"Прекратить залог: договор № {p.contract.number}",
                         "Обязательства исполнены. Подать уведомление об исключении сведений о залоге.",
                         link, f"pledge_release:{p.id}", due=today + timedelta(days=3)):
                created += 1
        else:
            created_at = p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=UTC)
            if now - created_at >= timedelta(days=PLEDGE_SETUP_DAYS) and open_task(
                    db, "pledge_setup", f"Решить вопрос о регистрации залога: договор № {p.contract.number}",
                    "Залог в статусе «планируется» больше недели. "
                    "Подготовить документы или отметить, что не требуется.",
                    link, f"pledge_setup:{p.id}", due=today + timedelta(days=3)):
                created += 1

    horizon = today + timedelta(days=INSURANCE_WARN_DAYS)
    for ins in db.scalars(select(InsurancePolicy).where(InsurancePolicy.required_by_contract.is_(True),
                                                        InsurancePolicy.valid_to <= horizon)):
        title = (f"Полис {ins.kind.value.upper()} № {ins.number} истекает {ins.valid_to:%d.%m.%Y}"
                 if ins.valid_to >= today else f"Полис {ins.kind.value.upper()} № {ins.number} истёк")
        if open_task(db, "insurance", title, f"{ins.car.make} {ins.car.model}. Запросить у покупателя новый полис.",
                     f"/contracts/{ins.contract_id}" if ins.contract_id else "/collateral",
                     f"insurance:{ins.id}:{ins.valid_to}", due=ins.valid_to):
            notify_staff(db, "insurance.expiring", title, "", "/collateral")
            created += 1

    for d in db.scalars(select(Document).where(Document.status == DocumentStatus.pending_approval)):
        submitted = d.submitted_at if d.submitted_at and d.submitted_at.tzinfo else (
            d.submitted_at.replace(tzinfo=UTC) if d.submitted_at else now)
        if now - submitted >= timedelta(days=1) and open_task(
                db, "document_approval", f"Утвердить документ: {d.title}", "Документ ожидает утверждения больше суток.",
                f"/documents/{d.id}", f"document_approval:{d.id}", due=today):
            created += 1

    for e in db.scalars(select(TaxCalendarEvent).where(TaxCalendarEvent.status == "open",
                                                       TaxCalendarEvent.due_date <= today + timedelta(days=7))):
        if open_task(db, "tax_deadline", f"Налоговый срок {e.due_date:%d.%m.%Y}: {e.title}",
                     "Подготовить и проверить. Подача отчётности и уплата — только с подтверждения владельца.",
                     "/accounting", f"tax_deadline:{e.id}", due=e.due_date):
            created += 1

    # Старые выполненные служебные задачи очереди больше не нужны
    db.execute(delete(Job).where(Job.status == JobStatus.done, Job.finished_at < now - timedelta(days=30)))
    return created


def close_task(task: StaffTask, user_id, note: str, now: datetime) -> None:
    task.status = TaskStatus.done
    task.done_at = now
    task.done_by = user_id
    task.result_note = note
