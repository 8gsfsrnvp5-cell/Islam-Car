"""Остаток долга, просрочка и статусы строк графика.

Распределение подтверждённых платежей по графику не хранится — оно вычисляется
каждый раз (FIFO по порядку строк графика). Поэтому сторнирование ошибочного платежа
автоматически и без рассинхронизации пересчитывает всё.

Просрочка не увеличивает долг: никаких процентов, пеней и штрафов здесь нет и быть не должно.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class LedgerRow:
    seq: int
    kind: str
    due_date: date
    amount_kopecks: int
    paid_kopecks: int
    remaining_kopecks: int
    status: str  # paid | partial | overdue | due_today | upcoming


@dataclass(frozen=True)
class LedgerSummary:
    total_kopecks: int
    paid_kopecks: int
    outstanding_kopecks: int
    overdue_kopecks: int
    overdue_items: int
    oldest_overdue_date: date | None
    next_due_date: date | None
    next_due_kopecks: int
    rows: list[LedgerRow]


def compute_ledger(items: list[tuple[int, str, date, int]], confirmed_total_kopecks: int,
                   today: date) -> LedgerSummary:
    """items: (seq, kind, due_date, amount) в любом порядке."""
    if confirmed_total_kopecks < 0:
        raise ValueError("Сумма подтверждённых платежей не может быть отрицательной")

    pool = confirmed_total_kopecks
    rows: list[LedgerRow] = []
    for seq, kind, due, amount in sorted(items, key=lambda it: it[0]):
        paid = min(amount, pool)
        pool -= paid
        remaining = amount - paid
        if remaining == 0:
            status = "paid"
        elif due < today:
            status = "overdue"
        elif due == today:
            status = "due_today"
        elif paid > 0:
            status = "partial"
        else:
            status = "upcoming"
        rows.append(LedgerRow(seq, kind, due, amount, paid, remaining, status))

    total = sum(r.amount_kopecks for r in rows)
    paid_total = sum(r.paid_kopecks for r in rows)
    overdue_rows = [r for r in rows if r.status == "overdue"]
    next_row = next((r for r in rows if r.remaining_kopecks > 0), None)
    return LedgerSummary(
        total_kopecks=total,
        paid_kopecks=paid_total,
        outstanding_kopecks=total - paid_total,
        overdue_kopecks=sum(r.remaining_kopecks for r in overdue_rows),
        overdue_items=len(overdue_rows),
        oldest_overdue_date=overdue_rows[0].due_date if overdue_rows else None,
        next_due_date=next_row.due_date if next_row else None,
        next_due_kopecks=next_row.remaining_kopecks if next_row else 0,
        rows=rows,
    )
