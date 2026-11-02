"""Чистая арифметика: график и распределение платежей."""

from datetime import date

import pytest

from app.services.ledger import compute_ledger
from app.services.schedule import Terms, TermsError, add_months, build_schedule

RUB = 100


def terms(**kw) -> Terms:
    base = dict(purchase_price_kopecks=1_200_000 * RUB, sale_price_kopecks=1_600_000 * RUB,
                down_payment_kopecks=600_000 * RUB, term_months=20,
                contract_date=date(2026, 11, 1), first_payment_date=date(2026, 12, 15))
    base.update(kw)
    return Terms(**base)


def test_example_from_business_model():
    """Пример из ТЗ: 1 200 000 → 1 600 000, взнос 600 000, 20 месяцев по 50 000."""
    t = terms()
    items = build_schedule(t)
    assert t.markup_kopecks == 400_000 * RUB
    assert t.financed_kopecks == 1_000_000 * RUB
    assert items[0].kind == "down_payment" and items[0].amount_kopecks == 600_000 * RUB
    installments = [i for i in items if i.kind == "installment"]
    assert len(installments) == 20
    assert {i.amount_kopecks for i in installments} == {50_000 * RUB}
    assert sum(i.amount_kopecks for i in items) == 1_600_000 * RUB
    assert installments[0].due_date == date(2026, 12, 15)
    assert installments[-1].due_date == date(2028, 7, 15)


def test_rounding_goes_to_last_payment():
    items = build_schedule(terms(sale_price_kopecks=1_000_000 * RUB, down_payment_kopecks=0, term_months=3))
    amounts = [i.amount_kopecks for i in items]
    assert amounts == [333_333 * RUB, 333_333 * RUB, 333_334 * RUB]
    assert sum(amounts) == 1_000_000 * RUB


def test_month_end_is_clamped():
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2027, 1, 31), 2) == date(2027, 3, 31)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


@pytest.mark.parametrize("kw", [
    {"down_payment_kopecks": 1_600_000 * RUB},
    {"down_payment_kopecks": -1},
    {"term_months": 0},
    {"term_months": 121},
    {"first_payment_date": date(2026, 11, 1)},
    {"purchase_price_kopecks": 0},
])
def test_invalid_terms_rejected(kw):
    with pytest.raises(TermsError):
        build_schedule(terms(**kw))


def test_ledger_fifo_and_no_penalties():
    items = [(0, "down_payment", date(2026, 1, 1), 100), (1, "installment", date(2026, 2, 1), 50),
             (2, "installment", date(2026, 3, 1), 50), (3, "installment", date(2026, 4, 1), 50)]
    lg = compute_ledger(items, confirmed_total_kopecks=130, today=date(2026, 3, 10))
    assert [r.paid_kopecks for r in lg.rows] == [100, 30, 0, 0]
    assert [r.status for r in lg.rows] == ["paid", "overdue", "overdue", "upcoming"]
    assert lg.overdue_kopecks == 70
    # Просрочка не увеличивает долг: итог равен сумме графика
    assert lg.total_kopecks == 250 and lg.outstanding_kopecks == 120
    assert lg.next_due_date == date(2026, 2, 1) and lg.next_due_kopecks == 20


def test_ledger_due_today_and_fully_paid():
    items = [(1, "installment", date(2026, 3, 10), 50), (2, "installment", date(2026, 4, 10), 50)]
    lg = compute_ledger(items, 0, date(2026, 3, 10))
    assert lg.rows[0].status == "due_today" and lg.overdue_kopecks == 0
    lg = compute_ledger(items, 100, date(2027, 1, 1))
    assert lg.outstanding_kopecks == 0 and lg.overdue_kopecks == 0 and lg.next_due_date is None
