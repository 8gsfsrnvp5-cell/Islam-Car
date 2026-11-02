"""Изменение графика дополнительным соглашением.

Цена договора не меняется: внесённые платежи сохраняются как оплаченные строки, а неоплаченный
остаток распределяется на новый срок. Никаких надбавок за отсрочку — это проверяется арифметически.
"""

from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Addendum,
    AddendumStatus,
    Contract,
    ContractStatus,
    ScheduleHistory,
    ScheduleItem,
    ScheduleKind,
)
from app.services.contracts import ledger_for
from app.services.schedule import MAX_TERM_MONTHS, add_months, monthly_amount


def plan_schedule(db: Session, contract: Contract, term_months: int, first_payment_date: date,
                  today: date) -> tuple[list[dict], int, list[dict]]:
    """Новый график, сумма уже внесённых платежей и результаты проверок."""
    if contract.status != ContractStatus.signed:
        raise HTTPException(409, "График меняется только у действующего договора")
    if not 1 <= term_months <= MAX_TERM_MONTHS:
        raise HTTPException(422, f"Срок — от 1 до {MAX_TERM_MONTHS} месяцев")
    if first_payment_date < today:
        raise HTTPException(422, "Первый платёж по новому графику не может быть в прошлом")
    ledger = ledger_for(db, contract, today)
    remaining = ledger.outstanding_kopecks
    if remaining <= 0:
        raise HTTPException(409, "Долг погашен — менять график не нужно")

    kept = [{"seq": r.seq, "kind": r.kind, "due_date": r.due_date.isoformat(), "amount_kopecks": r.paid_kopecks}
            for r in ledger.rows if r.paid_kopecks > 0]
    base = monthly_amount(remaining, term_months)
    if base <= 0:
        raise HTTPException(422, "Остаток слишком мал для выбранного срока")
    last = remaining - base * (term_months - 1)
    start_seq = max((r["seq"] for r in kept), default=0) + 1
    new_rows = kept + [{"seq": start_seq + i, "kind": "installment",
                        "due_date": add_months(first_payment_date, i).isoformat(),
                        "amount_kopecks": last if i == term_months - 1 else base} for i in range(term_months)]

    total = sum(r["amount_kopecks"] for r in new_rows)
    checks = [
        {"code": "price_unchanged", "ok": total == contract.sale_price_kopecks,
         "message": "Цена договора не изменилась" if total == contract.sale_price_kopecks
         else "Сумма нового графика не равна цене договора"},
        {"code": "paid_preserved", "ok": sum(r["amount_kopecks"] for r in kept) == ledger.paid_kopecks,
         "message": "Все внесённые платежи сохранены в графике"},
        {"code": "no_extra_charges", "ok": True,
         "message": "Надбавки, проценты и штрафы за отсрочку не начисляются"},
    ]
    if not all(c["ok"] for c in checks):
        raise HTTPException(500, "Нарушен инвариант графика — изменение отклонено")
    return new_rows, ledger.paid_kopecks, checks


def create_addendum(db: Session, contract: Contract, term_months: int, first_payment_date: date, reason: str,
                    thread_id, user_id, today: date) -> Addendum:
    if db.scalar(select(Addendum.id).where(Addendum.contract_id == contract.id,
                                           Addendum.status == AddendumStatus.draft)):
        raise HTTPException(409, "По договору уже есть неподписанное дополнительное соглашение")
    new_rows, paid, _ = plan_schedule(db, contract, term_months, first_payment_date, today)
    number = (db.scalar(select(func.max(Addendum.number)).where(Addendum.contract_id == contract.id)) or 0) + 1
    old = [{"seq": i.seq, "kind": i.kind.value, "due_date": i.due_date.isoformat(), "amount_kopecks": i.amount_kopecks}
           for i in contract.schedule]
    addendum = Addendum(contract_id=contract.id, number=number, reason=reason, thread_id=thread_id,
                        term_months=term_months, first_payment_date=first_payment_date, old_schedule=old,
                        new_schedule=new_rows, base_paid_kopecks=paid, created_by=user_id)
    db.add(addendum)
    db.flush()
    return addendum


def apply_addendum(db: Session, addendum: Addendum, signed_on: date, today: date) -> None:
    """Вызывается при фиксации подписания соглашения. Прежний график уходит в историю."""
    contract = db.get(Contract, addendum.contract_id)
    if addendum.status != AddendumStatus.draft:
        raise HTTPException(409, "Соглашение уже подписано или отменено")
    if contract.status != ContractStatus.signed:
        raise HTTPException(409, "Договор не действует")
    ledger = ledger_for(db, contract, today)
    if ledger.paid_kopecks != addendum.base_paid_kopecks:
        raise HTTPException(409, "После подготовки соглашения изменились платежи — подготовьте соглашение заново")
    for item in contract.schedule:
        db.add(ScheduleHistory(contract_id=contract.id, version=contract.schedule_version, seq=item.seq,
                               kind=item.kind.value, due_date=item.due_date, amount_kopecks=item.amount_kopecks,
                               replaced_by_addendum_id=addendum.id))
    contract.schedule.clear()
    db.flush()
    contract.schedule.extend(ScheduleItem(seq=r["seq"], kind=ScheduleKind(r["kind"]),
                                          due_date=date.fromisoformat(r["due_date"]),
                                          amount_kopecks=r["amount_kopecks"]) for r in addendum.new_schedule)
    contract.schedule_version += 1
    addendum.status = AddendumStatus.signed
    addendum.signed_on = signed_on
    assert sum(i.amount_kopecks for i in contract.schedule) == contract.sale_price_kopecks
