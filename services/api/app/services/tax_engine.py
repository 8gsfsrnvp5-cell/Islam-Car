"""Проверяемые налоговые формулы. Чистые функции: все ставки, лимиты и сроки приходят параметрами.

Параметры вносит бухгалтер со ссылкой на официальный источник и утверждает владелец — без утверждённого
параметра расчёт не выполняется (статус not_configured). Каждый результат показывает шаги, исходные данные,
использованные параметры и нормы. Это расчёт для проверки, а не декларация.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class Param:
    code: str
    value: Decimal
    effective_from: date
    effective_to: date | None
    source_url: str
    knowledge_code: str
    approved_by: str


@dataclass
class Result:
    code: str
    title: str
    status: str  # ok | not_configured | insufficient_data | not_applicable
    amount_kopecks: int | None = None
    steps: list[dict] = field(default_factory=list)
    params: list[dict] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)

    def step(self, label: str, value: int | None = None, text: str = "") -> None:
        self.steps.append({"label": label, "value_kopecks": value, "text": text})

    def use(self, p: Param) -> None:
        self.params.append({"code": p.code, "value": str(p.value), "effective_from": p.effective_from,
                            "effective_to": p.effective_to, "source_url": p.source_url,
                            "knowledge_code": p.knowledge_code, "approved_by": p.approved_by})


def pct(base_kopecks: int, rate: Decimal) -> int:
    return int((Decimal(base_kopecks) * rate / Decimal(100)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def missing(result: Result, *names: str) -> Result:
    result.status = "not_configured"
    result.warnings.append("Нет утверждённых параметров: " + ", ".join(names) +
                           ". Внесите их со ссылкой на источник и утвердите — расчёт не выполняется по предположениям.")
    return result


def usn_income(income: int, receipts: list[dict], rate: Param | None) -> Result:
    r = Result("usn_income", "УСН «доходы»: налог за период", "ok",
               basis=["acc.nk.346_14", "acc.nk.346_17", "acc.nk.346_20", "acc.nk.346_21"])
    r.inputs = {"receipts": receipts}
    r.step("Доходы — поступления денег за период (кассовый метод)", income, f"{len(receipts)} поступлений")
    if rate is None:
        return missing(r, "ставка УСН «доходы»")
    r.use(rate)
    tax = pct(income, rate.value)
    r.step(f"Налог = доходы × {rate.value}%", tax)
    r.amount_kopecks = tax
    r.warnings.append("Уменьшение налога на страховые взносы и ранее уплаченные авансы не учтено — "
                      "проверяет бухгалтер.")
    return r


def usn_income_expense(income: int, receipts: list[dict], expenses: list[dict], rate: Param | None,
                       min_rate: Param | None) -> Result:
    r = Result("usn_income_expense", "УСН «доходы минус расходы»: налог за период", "ok",
               basis=["acc.nk.346_14", "acc.nk.346_16", "acc.nk.346_17", "acc.nk.346_18", "acc.nk.346_20"])
    total_expenses = sum(e["amount_kopecks"] for e in expenses)
    r.inputs = {"receipts": receipts, "expenses": expenses}
    r.step("Доходы — поступления денег за период", income, f"{len(receipts)} поступлений")
    r.step("Расходы, принятые методикой", total_expenses, f"{len(expenses)} операций")
    names = [n for n, p in (("ставка УСН «доходы минус расходы»", rate), ("ставка минимального налога", min_rate))
             if p is None]
    if names:
        return missing(r, *names)
    r.use(rate)
    r.use(min_rate)
    base = income - total_expenses
    r.step("Налоговая база = доходы − расходы", base)
    tax = pct(max(base, 0), rate.value)
    r.step(f"Налог = база × {rate.value}%", tax)
    minimum = pct(income, min_rate.value)
    r.step(f"Минимальный налог = доходы × {min_rate.value}%", minimum)
    r.amount_kopecks = max(tax, minimum)
    r.step("К уплате — большее из двух значений", r.amount_kopecks)
    if base < 0:
        r.warnings.append("Получен убыток: перенос убытка на будущие периоды не учтён.")
    r.warnings.append("Методика признания расходов на покупку автомобилей (по мере реализации и при условии оплаты "
                      "поставщику) требует подтверждения бухгалтером.")
    return r


def ndfl_property(sales: list[dict], rate: Param | None, deduction: Param | None, holding: Param | None) -> Result:
    """sales: number, price, cost, purchase_date, sale_date, received_in_period (копейки)."""
    r = Result("ndfl_property", "НДФЛ с продажи автомобилей физическим лицом (оценка)", "ok",
               basis=["acc.nk.217_1", "acc.nk.220", "acc.nk.224", "acc.nk.228"])
    r.inputs = {"sales": sales}
    if not sales:
        r.status = "not_applicable"
        r.step("Поступлений по договорам в периоде нет", 0)
        return r
    names = [n for n, p in (("ставка НДФЛ", rate), ("предельный вычет", deduction),
                            ("минимальный срок владения", holding)) if p is None]
    if names:
        return missing(r, *names)
    for p in (rate, deduction, holding):
        r.use(p)
    total = 0
    for s in sales:
        label = f"Договор № {s['number']}"
        if s["purchase_date"] is None:
            r.warnings.append(f"{label}: не указана дата покупки автомобиля — срок владения не определён.")
            r.status = "insufficient_data"
            continue
        years = (s["sale_date"] - s["purchase_date"]).days / 365.25
        if years >= float(holding.value):
            r.step(f"{label}: срок владения {years:.1f} г. ≥ {holding.value} — доход освобождается", 0)
            continue
        cap = int(deduction.value * 100)
        reduce = max(cap, s["cost"] or 0)
        taxable_total = max(s["price"] - reduce, 0)
        share = Decimal(s["received_in_period"]) / Decimal(s["price"]) if s["price"] else Decimal(0)
        taxable = int((Decimal(taxable_total) * share).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        tax = pct(taxable, rate.value)
        r.step(f"{label}: цена − max(вычет, расходы на покупку) = облагаемая сумма по договору", taxable_total)
        r.step(f"{label}: доля поступлений в периоде {share:.4f} → облагаемый доход", taxable)
        r.step(f"{label}: налог × {rate.value}%", tax)
        total += tax
    r.amount_kopecks = total
    r.warnings.append("Распределение дохода и вычета по годам при оплате в рассрочку выполнено пропорционально "
                      "поступлениям — методику подтверждает бухгалтер. Декларацию подаёт сам продавец.")
    return r


def vat_margin(sales: list[dict], vat_payer: bool, rate: Param | None) -> Result:
    """sales: number, price, cost, purchased_from, signed_at."""
    r = Result("vat_margin", "НДС с межценовой разницы при продаже автомобилей", "ok",
               basis=["acc.nk.145", "acc.nk.154_5_1", "acc.nk.164"])
    r.inputs = {"sales": sales}
    if not vat_payer:
        r.status = "not_applicable"
        r.step("В налоговом профиле компания не отмечена как плательщик НДС", None)
        return r
    if rate is None:
        return missing(r, "ставка НДС")
    r.use(rate)
    total = 0
    for s in sales:
        label = f"Договор № {s['number']}"
        if s["purchased_from"] != "individual":
            r.warnings.append(f"{label}: автомобиль куплен не у физического лица или источник не указан — "
                              f"НДС по общему порядку рассчитывает бухгалтер.")
            r.status = "insufficient_data"
            continue
        margin = max(s["price"] - (s["cost"] or 0), 0)
        tax = int((Decimal(margin) * rate.value / (Decimal(100) + rate.value))
                  .quantize(Decimal(1), rounding=ROUND_HALF_UP))
        r.step(f"{label}: межценовая разница {margin / 100:,.2f} ₽ × {rate.value}/(100+{rate.value})".replace(",", " "),
               tax)
        total += tax
    r.amount_kopecks = total
    r.warnings.append("Момент определения базы (отгрузка или предварительная оплата) и счета-фактуры "
                      "проверяет бухгалтер.")
    return r
