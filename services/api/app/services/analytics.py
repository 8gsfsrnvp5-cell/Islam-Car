"""Расширенная аналитика: план и факт поступлений, просрочка по срокам, продажи, заявки, управленческий прогноз.

Все цифры — из подтверждённых платежей и графиков договоров. Прогноз помечается как прогноз;
вероятность неплатежа берётся из методики резерва, которую утверждает владелец, а не придумывается.
"""

from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, ApplicationStatus, Payment, PaymentStatus
from app.services.common import sum_kopecks, today
from app.services.contracts import get_company
from app.services.dashboard import live_ledgers
from app.services.finance_model import BUCKET_TITLES, DEFAULT_POLICY, aging_bucket, month_key, months_from, pct
from app.services.schedule import add_months

SOURCE_TITLES = {"staff": "внесено сотрудником", "bank_statement": "из банковской выписки",
                 "provider": "онлайн-оплата"}
FUNNEL = [
    ("all", "Заявки"),
    ("worked", "Взяты в работу"),
    ("offer_made", "Сделано предложение"),
    ("converted", "Заключён договор"),
]


def share(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def local_month(dt: datetime) -> str:
    aware = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return month_key(aware.astimezone(ZoneInfo(get_settings().company_timezone)).date())


def build(db: Session, months: int, with_finance: bool, on: date | None = None) -> dict[str, Any]:
    on = on or today()
    first = add_months(on.replace(day=1), -(months - 1))
    past = months_from(first, months)
    ledgers = live_ledgers(db, on)

    # План по графикам и факт по подтверждённым платежам
    planned: dict[str, int] = defaultdict(int)
    for _, lg in ledgers:
        for r in lg.rows:
            planned[month_key(r.due_date)] += r.amount_kopecks
    collected: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    pays = db.execute(select(Payment.received_on, Payment.source, sum_kopecks(Payment.amount_kopecks))
                      .where(Payment.status == PaymentStatus.confirmed, Payment.received_on >= first)
                      .group_by(Payment.received_on, Payment.source))
    for received_on, source, amount in pays:
        collected[month_key(received_on)][source] += int(amount or 0)
    monthly = []
    for m in past:
        got = sum(collected[m].values())
        monthly.append({"month": m, "planned_kopecks": planned.get(m, 0), "collected_kopecks": got,
                        "collection_rate": share(got, planned.get(m, 0)),
                        "by_source": {s: collected[m].get(s, 0) for s in SOURCE_TITLES}})

    # Продажи: подписанные договоры по месяцам
    sales: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "volume_kopecks": 0, "markup_kopecks": 0})
    for c, _ in ledgers:
        if c.signed_at and c.signed_at >= first:
            s = sales[month_key(c.signed_at)]
            s["count"] += 1
            s["volume_kopecks"] += c.sale_price_kopecks
            s["markup_kopecks"] += c.markup_kopecks
    sales_rows = [{"month": m, **sales.get(m, {"count": 0, "volume_kopecks": 0, "markup_kopecks": 0})}
                  for m in past]
    if not with_finance:
        for row in sales_rows:
            row.pop("markup_kopecks")

    # Просрочка по срокам
    aging = {b: {"title": t, "amount_kopecks": 0, "contracts": 0} for b, t in BUCKET_TITLES.items()}
    worst: dict[str, str] = {}
    for c, lg in ledgers:
        for r in lg.rows:
            if r.status == "overdue" and r.remaining_kopecks > 0:
                aging[aging_bucket((on - r.due_date).days)]["amount_kopecks"] += r.remaining_kopecks
        if lg.oldest_overdue_date:
            worst[str(c.id)] = aging_bucket((on - lg.oldest_overdue_date).days)
    for b in worst.values():
        aging[b]["contracts"] += 1

    # Заявки по месяцам и воронка
    since = datetime.combine(first, datetime.min.time(), tzinfo=UTC)
    apps = db.execute(select(Application.created_at, Application.status).where(Application.created_at >= since)).all()
    apps_by_month: dict[str, int] = defaultdict(int)
    stage = {"all": 0, "worked": 0, "offer_made": 0, "converted": 0}
    rejected = 0
    for created_at, status in apps:
        apps_by_month[local_month(created_at)] += 1
        stage["all"] += 1
        if status != ApplicationStatus.new:
            stage["worked"] += 1
        if status in (ApplicationStatus.offer_made, ApplicationStatus.converted):
            stage["offer_made"] += 1
        if status == ApplicationStatus.converted:
            stage["converted"] += 1
        if status in (ApplicationStatus.rejected, ApplicationStatus.withdrawn):
            rejected += 1
    funnel = [{"code": code, "title": title, "count": stage[code], "share": share(stage[code], stage["all"])}
              for code, title in FUNNEL]

    receivables = sum(lg.outstanding_kopecks for _, lg in ledgers)
    overdue = sum(lg.overdue_kopecks for _, lg in ledgers)
    closed = [row for row in monthly if row["month"] < month_key(on)][-3:]
    plan3, got3 = sum(r["planned_kopecks"] for r in closed), sum(r["collected_kopecks"] for r in closed)
    data = {
        "today": on, "months": past,
        "kpi": {"receivables_kopecks": receivables, "overdue_kopecks": overdue,
                "overdue_share": share(overdue, receivables), "collection_rate_3m": share(got3, plan3),
                "contracts_overdue": len(worst), "applications": stage["all"],
                "conversion": share(stage["converted"], stage["all"])},
        "monthly": monthly, "sales": sales_rows, "aging": [{"code": b, **v} for b, v in aging.items()],
        "applications": [{"month": m, "count": apps_by_month.get(m, 0)} for m in past],
        "funnel": funnel, "applications_closed_without_deal": rejected,
        "forecast": forecast(db, ledgers, on, 12),
        "notes": [
            "План — по действующим графикам договоров (с учётом дополнительных соглашений).",
            "Факт — только подтверждённые платежи: сотрудником, по банковской выписке или проверенной онлайн-оплатой.",
            "Собираемость = поступило за месяц / причиталось по графику в этом месяце. Оплата просрочки прошлых "
            "месяцев попадает в месяц поступления, поэтому значение может быть больше 100%.",
        ],
    }
    return data


def forecast(db: Session, ledgers, on: date, months: int) -> dict[str, Any]:
    """Управленческий прогноз поступлений: по графику и с учётом риска по методике резерва владельца."""
    policy = get_company(db).reserve_policy or {}
    aging = {**DEFAULT_POLICY["aging"], **(policy.get("aging") or {})}
    keys = months_from(on, months)
    scheduled: dict[str, int] = defaultdict(int)
    weighted: dict[str, int] = defaultdict(int)
    overdue_recovery = 0
    for _, lg in ledgers:
        bucket = aging_bucket((on - lg.oldest_overdue_date).days) if lg.oldest_overdue_date else None
        risk = aging[bucket] if bucket else 0
        for r in lg.rows:
            if r.remaining_kopecks <= 0:
                continue
            if r.status == "overdue":
                overdue_recovery += r.remaining_kopecks - pct(r.remaining_kopecks, aging[aging_bucket(
                    (on - r.due_date).days)])
                continue
            k = month_key(r.due_date)
            if k in keys:
                scheduled[k] += r.remaining_kopecks
                weighted[k] += r.remaining_kopecks - pct(r.remaining_kopecks, risk)
    rows = [{"month": k, "scheduled_kopecks": scheduled.get(k, 0), "risk_adjusted_kopecks": weighted.get(k, 0)}
            for k in keys]
    warnings = []
    if not policy.get("approved_at"):
        warnings.append("Методика резерва не утверждена владельцем — использованы значения по умолчанию")
    return {
        "label": "ПРОГНОЗ",
        "rows": rows,
        "overdue_recovery_kopecks": overdue_recovery,
        "method": ("«По графику» — неоплаченные платежи будущих месяцев. «С учётом риска» — то же, уменьшенное "
                   "по договорам с просрочкой на процент возможных неплатежей из методики резерва: "
                   + ", ".join(f"{BUCKET_TITLES[b]} — {aging[b]}%" for b in aging)
                   + ". Просроченные суммы показаны отдельно как возможное погашение без привязки к месяцу."),
        "warnings": warnings,
        "note": "Прогноз не является фактическим поступлением или прибылью.",
    }
