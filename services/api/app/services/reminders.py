"""Планировщик напоминаний: решает, какие сообщения нужны сегодня, и ставит их в очередь."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import Contract, ContractStatus, NotificationEvent
from app.services.contracts import ledger_for
from app.services.messaging import create_messages, ensure_default_rules


def company_date(now: datetime) -> date:
    return now.astimezone(ZoneInfo(get_settings().company_timezone)).date()


def row_context(contract: Contract, row, amount_kopecks: int) -> dict:
    return {"seq": row.seq, "due_date": row.due_date.isoformat(), "amount_kopecks": amount_kopecks,
            "schedule_version": contract.schedule_version}


def plan_reminders(db: Session, now: datetime) -> int:
    today = company_date(now)
    rules = [r for r in ensure_default_rules(db) if r.enabled]
    before = sorted((r for r in rules if r.event == NotificationEvent.before_due), key=lambda r: r.offset_days)
    due_rules = [r for r in rules if r.event == NotificationEvent.due_day]
    overdue = sorted((r for r in rules if r.event == NotificationEvent.overdue), key=lambda r: -r.offset_days)
    created = 0

    contracts = db.scalars(select(Contract).where(Contract.status == ContractStatus.signed)
                           .options(selectinload(Contract.schedule))).all()
    for c in contracts:
        ledger = ledger_for(db, c, today)
        for row in ledger.rows:
            if row.remaining_kopecks == 0:
                continue
            # Из нескольких правил «за N дней» берём самое позднее из уже наступивших — без дублей после простоя
            rule = next((r for r in before if row.due_date - timedelta(days=r.offset_days) <= today < row.due_date),
                        None)
            if rule:
                created += len(create_messages(db, c, NotificationEvent.before_due,
                                               f"v{c.schedule_version}:{row.seq}:{rule.offset_days}",
                                               row_context(c, row, row.remaining_kopecks), rule.channels, now))
            if row.due_date == today:
                for rule in due_rules:
                    created += len(create_messages(db, c, NotificationEvent.due_day, f"v{c.schedule_version}:{row.seq}",
                                                   row_context(c, row, row.remaining_kopecks), rule.channels, now))

        if ledger.oldest_overdue_date:
            oldest = next(r for r in ledger.rows if r.status == "overdue")
            days = (today - oldest.due_date).days
            rule = next((r for r in overdue if days >= r.offset_days), None)
            if rule:
                # В сообщении о просрочке — вся просроченная сумма по договору
                created += len(create_messages(db, c, NotificationEvent.overdue,
                                               f"v{c.schedule_version}:{oldest.seq}:{rule.offset_days}",
                                               row_context(c, oldest, ledger.overdue_kopecks), rule.channels, now))
    return created
