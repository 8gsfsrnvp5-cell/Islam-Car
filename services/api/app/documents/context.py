"""Данные для подстановки в шаблоны — только из проверенных карточек, без выдуманных значений."""

from datetime import date
from typing import Any

from num2words import num2words
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Addendum,
    Car,
    Client,
    Contract,
    PartyType,
    Payment,
    PaymentStatus,
)
from app.services.contracts import get_company, ledger_for
from app.services.messaging import plural

PARTY_LABEL = {"individual": "физическое лицо", "ip": "индивидуальный предприниматель",
               "llc": "общество с ограниченной ответственностью"}
REGIME_LABEL = {"individual_one_off": "физическое лицо", "ip": "индивидуальный предприниматель",
                "llc": "общество с ограниченной ответственностью"}
ROW_LABEL = {"paid": "оплачен", "partial": "оплачен частично", "overdue": "просрочен", "due_today": "срок сегодня",
             "upcoming": "предстоит"}

# Подписи обязательных полей для сообщения «не хватает данных»
FIELD_LABELS = {
    "seller.name": "наименование/ФИО продавца (Настройки)", "seller.inn": "ИНН продавца (Настройки)",
    "seller.address": "адрес продавца (Настройки)", "seller.ogrn": "ОГРН/ОГРНИП продавца (Настройки)",
    "seller.bank_account": "расчётный счёт продавца (Настройки)", "seller.bank_bik": "БИК банка продавца (Настройки)",
    "seller.bank_name": "банк продавца (Настройки)",
    "client.full_name": "ФИО/наименование покупателя", "client.address": "адрес покупателя",
    "client.passport_number": "паспорт покупателя", "client.passport_issued_by": "кем выдан паспорт покупателя",
    "client.passport_issue_date": "дата выдачи паспорта покупателя", "client.birth_date": "дата рождения покупателя",
    "client.inn": "ИНН покупателя", "client.ogrn": "ОГРН/ОГРНИП покупателя", "client.phone": "телефон покупателя",
    "car.vin": "VIN автомобиля", "car.color": "цвет автомобиля",
    "car.purchase_document": "документ о покупке автомобиля",
    "contract.number": "номер договора (присваивается при подписании)",
    "contract.signed_at": "дата подписания договора",
    "addendum.number": "номер дополнительного соглашения",
    "client.identity_doc": "документ покупателя (паспорт для физлица, ИНН для ИП и ООО)",
    "ledger.next_due_date": "ближайший платёж по графику (все платежи внесены)",
    "ledger.has_overdue": "просроченная задолженность (по договору её нет)",
    "ledger.fully_paid": "полная оплата (договор ещё не оплачен полностью)",
}


def d(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def money(kopecks: int | None) -> str:
    if kopecks is None:
        return ""
    rubles, kop = divmod(kopecks, 100)
    return f"{rubles:,}".replace(",", " ") + f",{kop:02d} руб."


def money_words(kopecks: int | None) -> str:
    """1 600 000 (один миллион шестьсот тысяч) рублей 00 копеек — как принято в договорах."""
    if kopecks is None:
        return ""
    rubles, kop = divmod(kopecks, 100)
    return (f"{rubles:,}".replace(",", " ") + f" ({num2words(rubles, lang='ru')}) "
            f"{plural(rubles, 'рубль', 'рубля', 'рублей')} {kop:02d} {plural(kop, 'копейка', 'копейки', 'копеек')}")


def get_path(ctx: dict, path: str) -> Any:
    value: Any = ctx
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def missing_fields(ctx: dict, requires: list[str]) -> list[str]:
    def empty(value: Any) -> bool:
        return value is None or value is False or not str(value).strip()
    return [FIELD_LABELS.get(p, p) for p in requires if empty(get_path(ctx, p))]


def client_requisites(c: Client) -> str:
    if c.party_type == PartyType.individual:
        parts = [c.full_name]
        if c.birth_date:
            parts.append(f"{d(c.birth_date)} г. р.")
        if c.passport_number:
            issued = f"{c.passport_issued_by} {d(c.passport_issue_date)}".strip()
            parts.append(f"паспорт {c.passport_number}, выдан {issued}")
        if c.address:
            parts.append(f"адрес регистрации: {c.address}")
        return ", ".join(parts)
    if c.party_type == PartyType.ip:
        return (f"индивидуальный предприниматель {c.full_name}, ИНН {c.inn or '____'}, ОГРНИП {c.ogrn or '____'}, "
                f"адрес: {c.address}")
    return (f"{c.full_name} (ИНН {c.inn or '____'}, КПП {c.kpp or '____'}, ОГРН {c.ogrn or '____'}, "
            f"адрес: {c.address}), в лице {c.representative or '____'}")


def client_ctx(c: Client) -> dict:
    return {
        "full_name": c.full_name, "party_type": c.party_type.value, "party_label": PARTY_LABEL[c.party_type.value],
        "is_individual": c.party_type == PartyType.individual, "phone": c.phone, "email": c.email,
        "address": c.address, "birth_date": d(c.birth_date), "passport_number": c.passport_number,
        "passport_issued_by": c.passport_issued_by, "passport_issue_date": d(c.passport_issue_date),
        "inn": c.inn, "ogrn": c.ogrn, "kpp": c.kpp, "representative": c.representative,
        "identity_doc": c.passport_number if c.party_type == PartyType.individual else c.inn,
        "requisites": client_requisites(c),
    }


def car_ctx(car: Car) -> dict:
    return {"make": car.make, "model": car.model, "year": car.year, "vin": car.vin or "", "color": car.color,
            "engine": car.engine, "body_type": car.body_type, "mileage_km": f"{car.mileage_km:,}".replace(",", " "),
            "transmission": car.transmission, "purchase_document": car.purchase_document,
            "title": f"{car.make} {car.model}, {car.year} г. в."}


def build_context(db: Session, *, contract: Contract | None = None, client: Client | None = None,
                  car: Car | None = None, addendum: Addendum | None = None, params: dict | None = None,
                  today: date) -> dict:
    co = get_company(db)
    ctx: dict[str, Any] = {
        "today": d(today),
        "params": params or {},
        "seller": {"name": co.seller_name, "inn": co.seller_inn, "ogrn": co.seller_ogrn, "address": co.seller_address,
                   "regime": co.seller_regime.value, "regime_label": REGIME_LABEL[co.seller_regime.value],
                   "phone": co.support_phone, "bank_payee": co.bank_payee, "bank_name": co.bank_name,
                   "bank_bik": co.bank_bik, "bank_account": co.bank_account, "bank_corr_account": co.bank_corr_account,
                   "requisites": ", ".join(x for x in (
                       f"{REGIME_LABEL[co.seller_regime.value]} {co.seller_name}".strip(),
                       f"ИНН {co.seller_inn}" if co.seller_inn else "",
                       f"ОГРН {co.seller_ogrn}" if co.seller_ogrn else "",
                       f"адрес: {co.seller_address}" if co.seller_address else "") if x)},
    }
    if contract is not None:
        client = contract.client
        car = contract.car
        ledger = ledger_for(db, contract, today)
        ctx["contract"] = {
            "number": contract.number or "", "date": d(contract.contract_date), "signed_at": d(contract.signed_at),
            "status": contract.status.value, "is_consumer_deal": contract.is_consumer_deal,
            "disclose_cost": contract.disclose_cost_to_buyer,
            "sale_price": money(contract.sale_price_kopecks),
            "sale_price_words": money_words(contract.sale_price_kopecks),
            "purchase_price": money(contract.purchase_price_kopecks),
            "purchase_price_words": money_words(contract.purchase_price_kopecks),
            "markup": money(contract.markup_kopecks), "markup_words": money_words(contract.markup_kopecks),
            "down_payment": money(contract.down_payment_kopecks),
            "down_payment_words": money_words(contract.down_payment_kopecks),
            "has_down_payment": contract.down_payment_kopecks > 0,
            "financed": money(contract.financed_kopecks), "financed_words": money_words(contract.financed_kopecks),
            "term_months": contract.term_months, "monthly": money(contract.monthly_payment_kopecks),
            "monthly_words": money_words(contract.monthly_payment_kopecks),
            "first_payment_date": d(contract.first_payment_date), "payment_day": contract.first_payment_date.day,
            "schedule_version": contract.schedule_version,
            "last_payment_date": d(max((i.due_date for i in contract.schedule), default=None)),
        }
        ctx["schedule"] = [{"label": "Первоначальный взнос" if i.seq == 0 else f"Платёж № {i.seq}",
                            "date": d(i.due_date), "amount": money(i.amount_kopecks)} for i in contract.schedule]
        ctx["ledger"] = {
            "as_of": d(today), "total": money(ledger.total_kopecks), "paid": money(ledger.paid_kopecks),
            "paid_words": money_words(ledger.paid_kopecks), "outstanding": money(ledger.outstanding_kopecks),
            "outstanding_words": money_words(ledger.outstanding_kopecks), "overdue": money(ledger.overdue_kopecks),
            "overdue_words": money_words(ledger.overdue_kopecks), "has_overdue": ledger.overdue_kopecks > 0,
            "oldest_overdue_date": d(ledger.oldest_overdue_date), "next_due_date": d(ledger.next_due_date),
            "next_due": money(ledger.next_due_kopecks), "next_due_words": money_words(ledger.next_due_kopecks),
            "fully_paid": ledger.outstanding_kopecks == 0,
            "rows": [{"label": "Первоначальный взнос" if r.seq == 0 else f"Платёж № {r.seq}", "date": d(r.due_date),
                      "amount": money(r.amount_kopecks), "paid": money(r.paid_kopecks),
                      "remaining": money(r.remaining_kopecks), "status": ROW_LABEL[r.status]} for r in ledger.rows],
        }
        payments = db.scalars(select(Payment).where(Payment.contract_id == contract.id,
                                                    Payment.status == PaymentStatus.confirmed)
                              .order_by(Payment.received_on)).all()
        ctx["payments"] = [{"date": d(p.received_on), "amount": money(p.amount_kopecks), "document": p.document_ref}
                           for p in payments]
    if addendum is not None:
        ctx["addendum"] = {
            "number": str(addendum.number), "date": d(addendum.signed_on or today), "reason": addendum.reason,
            "term_months": addendum.term_months, "first_payment_date": d(addendum.first_payment_date),
            "paid_before": money(addendum.base_paid_kopecks),
            "rows": [{"label": "Первоначальный взнос" if r["seq"] == 0 else f"Платёж № {r['seq']}",
                      "date": d(date.fromisoformat(r["due_date"])), "amount": money(r["amount_kopecks"])}
                     for r in addendum.new_schedule],
        }
    if client is not None:
        ctx["client"] = client_ctx(client)
    if car is not None:
        ctx["car"] = car_ctx(car)
    return ctx
