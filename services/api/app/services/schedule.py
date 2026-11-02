"""Построение графика платежей. Чистые функции без доступа к базе — легко проверить тестами."""

import calendar
from dataclasses import dataclass
from datetime import date

KOPECKS_IN_RUBLE = 100
MAX_TERM_MONTHS = 120


class TermsError(ValueError):
    pass


@dataclass(frozen=True)
class PlannedItem:
    seq: int
    kind: str  # down_payment | installment
    due_date: date
    amount_kopecks: int


@dataclass(frozen=True)
class Terms:
    purchase_price_kopecks: int
    sale_price_kopecks: int
    down_payment_kopecks: int
    term_months: int
    contract_date: date
    first_payment_date: date

    @property
    def markup_kopecks(self) -> int:
        return self.sale_price_kopecks - self.purchase_price_kopecks

    @property
    def financed_kopecks(self) -> int:
        return self.sale_price_kopecks - self.down_payment_kopecks


def validate_terms(t: Terms) -> list[str]:
    """Жёсткие ошибки арифметики. Пустой список — условия корректны."""
    errors: list[str] = []
    if t.purchase_price_kopecks <= 0:
        errors.append("Закупочная стоимость должна быть больше нуля")
    if t.sale_price_kopecks <= 0:
        errors.append("Цена продажи должна быть больше нуля")
    if t.down_payment_kopecks < 0:
        errors.append("Первоначальный взнос не может быть отрицательным")
    if t.down_payment_kopecks >= t.sale_price_kopecks:
        errors.append("Первоначальный взнос должен быть меньше цены продажи")
    if not 1 <= t.term_months <= MAX_TERM_MONTHS:
        errors.append(f"Срок должен быть от 1 до {MAX_TERM_MONTHS} месяцев")
    if t.first_payment_date <= t.contract_date:
        errors.append("Первый ежемесячный платёж должен быть позже даты договора")
    return errors


def add_months(anchor: date, months: int) -> date:
    """Тот же день месяца; если такого дня нет — последний день месяца (31 янв → 28/29 фев)."""
    month_index = anchor.month - 1 + months
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def monthly_amount(financed_kopecks: int, term_months: int) -> int:
    """Ежемесячный платёж, округлённый вниз до целого рубля."""
    per_month = financed_kopecks // term_months
    return per_month - per_month % KOPECKS_IN_RUBLE


def build_schedule(t: Terms) -> list[PlannedItem]:
    errors = validate_terms(t)
    if errors:
        raise TermsError("; ".join(errors))

    items: list[PlannedItem] = []
    if t.down_payment_kopecks > 0:
        items.append(PlannedItem(0, "down_payment", t.contract_date, t.down_payment_kopecks))

    base = monthly_amount(t.financed_kopecks, t.term_months)
    if base <= 0:
        raise TermsError("Сумма рассрочки слишком мала для выбранного срока")
    last = t.financed_kopecks - base * (t.term_months - 1)
    for i in range(t.term_months):
        amount = last if i == t.term_months - 1 else base
        items.append(PlannedItem(i + 1, "installment", add_months(t.first_payment_date, i), amount))

    assert sum(it.amount_kopecks for it in items) == t.sale_price_kopecks
    return items
