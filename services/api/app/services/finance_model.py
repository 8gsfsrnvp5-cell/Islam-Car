"""Финансовая модель: резерв, свободные деньги, сценарии. Чистые функции — легко проверить тестами.

Все результаты сценариев — прогнозы по графикам договоров, а не фактическая прибыль.
Коэффициенты резерва — управленческая методика владельца, не правовые нормы.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.services.schedule import add_months, monthly_amount

DEFAULT_POLICY = {"opex_months": 3, "aging": {"0_30": 10, "31_90": 30, "90_plus": 60}}
BUCKET_TITLES = {"0_30": "до 30 дн.", "31_90": "31–90 дн.", "90_plus": "более 90 дн."}


@dataclass(frozen=True)
class Flow:
    contract: str
    due_date: date
    amount_kopecks: int


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_from(start: date, count: int) -> list[str]:
    first = start.replace(day=1)
    return [month_key(add_months(first, i)) for i in range(count)]


def aging_bucket(days: int) -> str:
    if days <= 30:
        return "0_30"
    if days <= 90:
        return "31_90"
    return "90_plus"


def pct(amount: int, percent: Decimal | int | float) -> int:
    return int((Decimal(amount) * Decimal(str(percent)) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def reserve(policy: dict, monthly_opex: int, overdue: list[tuple[int, int]], tax_due: int | None) -> dict:
    """overdue: (сумма просрочки, дней просрочки). tax_due: None — налоговые правила не утверждены."""
    aging = {**DEFAULT_POLICY["aging"], **(policy.get("aging") or {})}
    months = policy.get("opex_months", DEFAULT_POLICY["opex_months"])
    buckets: dict[str, int] = defaultdict(int)
    for amount, days in overdue:
        buckets[aging_bucket(days)] += amount
    bad_debt = sum(pct(buckets[b], aging[b]) for b in aging)
    opex = int(monthly_opex * Decimal(str(months)))
    items = [
        {"code": "taxes", "title": "Налоги к уплате (по утверждённым правилам)", "amount_kopecks": tax_due or 0,
         "basis": "Расчёт бухгалтерского модуля с начала года минус уплаченные налоги" if tax_due is not None
         else "Не рассчитано: нет утверждённых налоговых правил — резерв на налоги не определён"},
        {"code": "opex", "title": f"Содержание бизнеса на {months} мес.", "amount_kopecks": opex,
         "basis": f"Средние фактические расходы за последние 3 месяца × {months}"},
        {"code": "bad_debt", "title": "Возможные неплатежи", "amount_kopecks": bad_debt,
         "basis": "Просрочка по срокам: " + ", ".join(
             f"{BUCKET_TITLES[b]} — {aging[b]}% от "
             f"{buckets[b] / 100:,.0f} ₽".replace(",", " ") for b in aging)},
    ]
    return {"items": items, "total_kopecks": sum(i["amount_kopecks"] for i in items),
            "taxes_known": tax_due is not None,
            "buckets": dict(buckets)}


def forecast(flows: list[Flow], start: date, months: int) -> dict[str, int]:
    keys = months_from(start, months)
    result = dict.fromkeys(keys, 0)
    for f in flows:
        k = month_key(f.due_date)
        if k in result:
            result[k] += f.amount_kopecks
    return result


def scenario_delay(flows: list[Flow], contracts: set[str], delay_months: int, start: date, months: int) -> dict:
    """Платежи выбранных договоров сдвигаются на N месяцев."""
    shifted = [Flow(f.contract, add_months(f.due_date, delay_months), f.amount_kopecks)
               if f.contract in contracts else f for f in flows]
    return _compare(forecast(flows, start, months), forecast(shifted, start, months))


def scenario_defaults(flows: list[Flow], contracts: set[str], from_month: date, start: date, months: int) -> dict:
    """Выбранные покупатели перестают платить с указанного месяца."""
    cut = from_month.replace(day=1)
    remaining = [f for f in flows if not (f.contract in contracts and f.due_date >= cut)]
    lost = sum(f.amount_kopecks for f in flows if f.contract in contracts and f.due_date >= cut)
    result = _compare(forecast(flows, start, months), forecast(remaining, start, months))
    result["lost_total_kopecks"] = lost
    return result


def _compare(base: dict[str, int], scenario: dict[str, int]) -> dict:
    rows = [{"month": m, "base_kopecks": base[m], "scenario_kopecks": scenario[m],
             "diff_kopecks": scenario[m] - base[m]} for m in base]
    return {"rows": rows, "base_total_kopecks": sum(base.values()), "scenario_total_kopecks": sum(scenario.values()),
            "diff_total_kopecks": sum(scenario.values()) - sum(base.values())}


def scenario_next_car(free_cash: int | None, purchase_kopecks: int, extra_kopecks: int,
                      monthly: dict[str, int]) -> dict:
    """Сколько не хватает на следующий автомобиль и когда это закроется ожидаемыми поступлениями."""
    need = purchase_kopecks + extra_kopecks
    if free_cash is None:
        return {"need_kopecks": need, "shortfall_kopecks": None, "covered_in": None,
                "note": "Внесите остаток денежных средств — без него свободные деньги не определены"}
    shortfall = max(need - free_cash, 0)
    covered_in = None
    acc = 0
    for m, amount in monthly.items():
        if shortfall == 0:
            covered_in = "сейчас"
            break
        acc += amount
        if acc >= shortfall:
            covered_in = m
            break
    return {"need_kopecks": need, "free_cash_kopecks": free_cash, "shortfall_kopecks": shortfall,
            "covered_in": covered_in or ("сейчас" if shortfall == 0 else None),
            "note": "Прогноз по графикам действующих договоров без учёта просрочек и новых расходов"}


def scenario_deals(deals: list[dict], start: date, months: int) -> dict:
    """Модель нескольких будущих продаж: закупка сейчас, взнос сразу, остаток равными платежами со следующего месяца."""
    cash = dict.fromkeys(months_from(start, months), 0)
    first = month_key(start)
    total_markup = total_purchase = 0
    for d in deals:
        purchase, price, down, term = d["purchase_kopecks"], d["sale_kopecks"], d["down_kopecks"], d["term_months"]
        if not (0 <= down < price) or term < 1:
            raise ValueError("Взнос должен быть меньше цены, срок — не меньше месяца")
        total_markup += price - purchase
        total_purchase += purchase
        cash[first] += down - purchase
        base = monthly_amount(price - down, term)
        last = price - down - base * (term - 1)
        for i in range(term):
            k = month_key(add_months(start.replace(day=1), i + 1))
            if k in cash:
                cash[k] += last if i == term - 1 else base
    running = 0
    payback = None
    rows = []
    for m, v in cash.items():
        running += v
        rows.append({"month": m, "net_kopecks": v, "cumulative_kopecks": running})
        if payback is None and running >= 0 and v != 0 and m != first:
            payback = m
    if payback is None and rows and rows[0]["cumulative_kopecks"] >= 0:
        payback = first
    return {"rows": rows, "total_markup_kopecks": total_markup, "total_purchase_kopecks": total_purchase,
            "max_cash_need_kopecks": -min((r["cumulative_kopecks"] for r in rows), default=0), "payback_month": payback,
            "note": "Наценка — по ценам сделок, это не прибыль: расходы и налоги не вычтены"}
