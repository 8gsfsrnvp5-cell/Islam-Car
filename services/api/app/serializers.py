"""Преобразование моделей в ответы API. Здесь решается, какие поля видит каждая сторона."""

from typing import Any

from app.models import (
    Application,
    Car,
    CarStatus,
    Client,
    Contract,
    OwnershipStatus,
    Payment,
    PaymentReport,
    SupportThread,
)
from app.security import Actor
from app.services.common import mask_phone, mask_tail
from app.services.ledger import LedgerSummary

PUBLIC_CAR_STATUSES = (CarStatus.available, CarStatus.reserved)


def availability(car: Car) -> str:
    """Что честно сказать покупателю о наличии автомобиля."""
    if car.status == CarStatus.reserved:
        return "reserved"
    if car.ownership_status == OwnershipStatus.owned:
        return "in_stock"
    return "purchasing"


def photo_urls(car: Car, scope: str) -> list[dict[str, Any]]:
    return [{"id": p.id, "url": f"/api/{scope}/cars/{car.id}/photos/{p.id}"} for p in car.photos]


def car_public(car: Car) -> dict[str, Any]:
    return {
        "id": car.id, "make": car.make, "model": car.model, "year": car.year,
        "mileage_km": car.mileage_km, "body_type": car.body_type, "engine": car.engine,
        "transmission": car.transmission, "drive": car.drive, "color": car.color,
        "trim": car.trim, "condition": car.condition, "description": car.description,
        "vin_tail": mask_tail(car.vin or "", 4) if car.vin else "",
        "availability": availability(car),
        "sale_price_kopecks": car.sale_price_kopecks,
        "min_down_payment_kopecks": car.min_down_payment_kopecks,
        "max_term_months": car.max_term_months,
        "photos": photo_urls(car, "public"),
    }


def car_staff(car: Car, actor: Actor) -> dict[str, Any]:
    data = car_public(car)
    data.update({
        "vin": car.vin, "ownership_status": car.ownership_status, "status": car.status,
        "is_published": car.is_published, "purchase_date": car.purchase_date,
        "purchase_document": car.purchase_document, "purchased_from": car.purchased_from,
        "created_at": car.created_at,
        "updated_at": car.updated_at, "photos": photo_urls(car, "admin"),
    })
    data.pop("vin_tail")
    if actor.can("cars.cost"):
        data["purchase_price_kopecks"] = car.purchase_price_kopecks
    return data


def car_short(car: Car | None) -> dict[str, Any] | None:
    if car is None:
        return None
    return {"id": car.id, "title": f"{car.make} {car.model}, {car.year}", "vin": car.vin}


def application_staff(a: Application, actor: Actor) -> dict[str, Any]:
    return {
        "id": a.id, "kind": a.kind, "status": a.status, "name": a.name,
        "phone": a.phone if actor.can("clients.pd") else mask_phone(a.phone),
        "car": car_short(a.car), "client_id": a.client_id,
        "desired_down_payment_kopecks": a.desired_down_payment_kopecks,
        "desired_term_months": a.desired_term_months, "comment": a.comment if actor.can("clients.pd") else "",
        "wanted_make": a.wanted_make, "wanted_model": a.wanted_model, "wanted_year": a.wanted_year,
        "wanted_trim": a.wanted_trim, "max_budget_kopecks": a.max_budget_kopecks,
        "consent_personal_data": a.consent_personal_data, "consent_version": a.consent_version,
        "public_message": a.public_message, "internal_note": a.internal_note if actor.can("clients.pd") else "",
        "public_token": a.public_token if actor.can("clients.pd") else "",
        "created_at": a.created_at, "updated_at": a.updated_at,
        "events": [{"from_status": e.from_status, "to_status": e.to_status,
                    "public_message": e.public_message, "created_at": e.created_at} for e in a.events],
    }


def application_public(a: Application) -> dict[str, Any]:
    return {
        "kind": a.kind, "status": a.status, "created_at": a.created_at, "updated_at": a.updated_at,
        "car_title": f"{a.car.make} {a.car.model}, {a.car.year}" if a.car else None,
        "wanted": f"{a.wanted_make} {a.wanted_model}".strip() or None,
        "public_message": a.public_message,
        "history": [{"status": e.to_status, "message": e.public_message, "at": e.created_at} for e in a.events],
    }


def client_staff(c: Client, actor: Actor) -> dict[str, Any]:
    full = actor.can("clients.pd")
    return {
        "id": c.id, "party_type": c.party_type, "full_name": c.full_name,
        "phone": c.phone if full else mask_phone(c.phone),
        "email": c.email if full else "", "address": c.address if full else ("указан" if c.address else ""),
        "birth_date": c.birth_date if full else None,
        "passport_number": c.passport_number if full else mask_tail(c.passport_number, 2),
        "passport_issued_by": c.passport_issued_by if full else "",
        "passport_issue_date": c.passport_issue_date if full else None,
        "inn": c.inn, "ogrn": c.ogrn, "kpp": c.kpp, "representative": c.representative,
        "timezone": c.timezone, "identity_verified": c.identity_verified,
        "identity_verified_at": c.identity_verified_at, "notes": c.notes if full else "",
        "has_cabinet_access": bool(c.user and c.user.password_hash and c.user.is_active),
        "cabinet_login": c.user.login if c.user and full else None,
        "created_at": c.created_at, "pd_masked": not full,
    }


def client_short(c: Client) -> dict[str, Any]:
    return {"id": c.id, "full_name": c.full_name, "party_type": c.party_type}


def ledger_dict(ledger: LedgerSummary, with_rows: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "total_kopecks": ledger.total_kopecks, "paid_kopecks": ledger.paid_kopecks,
        "outstanding_kopecks": ledger.outstanding_kopecks, "overdue_kopecks": ledger.overdue_kopecks,
        "overdue_items": ledger.overdue_items, "oldest_overdue_date": ledger.oldest_overdue_date,
        "next_due_date": ledger.next_due_date, "next_due_kopecks": ledger.next_due_kopecks,
    }
    if with_rows:
        data["rows"] = [{"seq": r.seq, "kind": r.kind, "due_date": r.due_date, "amount_kopecks": r.amount_kopecks,
                         "paid_kopecks": r.paid_kopecks, "remaining_kopecks": r.remaining_kopecks,
                         "status": r.status} for r in ledger.rows]
    return data


def contract_terms(c: Contract) -> dict[str, Any]:
    return {
        "sale_price_kopecks": c.sale_price_kopecks, "down_payment_kopecks": c.down_payment_kopecks,
        "financed_kopecks": c.financed_kopecks, "term_months": c.term_months,
        "monthly_payment_kopecks": c.monthly_payment_kopecks, "contract_date": c.contract_date,
        "first_payment_date": c.first_payment_date, "no_interest_on_delay": c.no_interest_on_delay,
    }


def contract_staff(c: Contract, ledger: LedgerSummary | None, actor: Actor, with_rows: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": c.id, "number": c.number, "status": c.status, "client": client_short(c.client),
        "car": car_short(c.car), "application_id": c.application_id,
        "seller_regime": c.seller_regime, "buyer_type": c.buyer_type, "is_consumer_deal": c.is_consumer_deal,
        "disclose_cost_to_buyer": c.disclose_cost_to_buyer, "signed_at": c.signed_at,
        "completed_at": c.completed_at, "notes": c.notes, "created_at": c.created_at,
        **contract_terms(c),
    }
    if actor.can("finance.read"):
        data["purchase_price_kopecks"] = c.purchase_price_kopecks
        data["markup_kopecks"] = c.markup_kopecks
    if ledger is not None:
        data["ledger"] = ledger_dict(ledger, with_rows)
    return data


def contract_client(c: Contract, ledger: LedgerSummary, with_rows: bool = True) -> dict[str, Any]:
    car = c.car
    data: dict[str, Any] = {
        "id": c.id, "number": c.number, "status": c.status, "signed_at": c.signed_at,
        "completed_at": c.completed_at,
        "car": {"title": f"{car.make} {car.model}, {car.year}", "vin": car.vin, "color": car.color,
                "make": car.make, "model": car.model, "year": car.year},
        **contract_terms(c),
        "ledger": ledger_dict(ledger, with_rows),
    }
    if c.disclose_cost_to_buyer:
        # Мурабаха: покупателю раскрываются себестоимость и наценка продавца
        data["purchase_price_kopecks"] = c.purchase_price_kopecks
        data["markup_kopecks"] = c.markup_kopecks
    return data


def payment_dict(p: Payment) -> dict[str, Any]:
    return {
        "id": p.id, "contract_id": p.contract_id, "amount_kopecks": p.amount_kopecks,
        "received_on": p.received_on, "method": p.method, "document_ref": p.document_ref,
        "note": p.note, "status": p.status, "confirmed_at": p.confirmed_at,
        "reversed_at": p.reversed_at, "reversal_reason": p.reversal_reason,
        "corrects_payment_id": p.corrects_payment_id, "report_id": p.report_id, "source": p.source,
        "external_ref": p.external_ref,
    }


def payment_client(p: Payment) -> dict[str, Any]:
    return {"id": p.id, "amount_kopecks": p.amount_kopecks, "received_on": p.received_on,
            "method": p.method, "status": p.status}


def report_dict(r: PaymentReport) -> dict[str, Any]:
    return {"id": r.id, "contract_id": r.contract_id, "amount_kopecks": r.amount_kopecks, "paid_on": r.paid_on,
            "comment": r.comment, "status": r.status, "review_note": r.review_note,
            "reviewed_at": r.reviewed_at, "created_at": r.created_at}


def thread_dict(t: SupportThread, with_messages: bool, for_staff: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": t.id, "topic": t.topic, "subject": t.subject, "status": t.status,
        "contract_id": t.contract_id, "created_at": t.created_at, "updated_at": t.updated_at,
    }
    if for_staff:
        data["client"] = client_short(t.client)
    if with_messages:
        data["messages"] = [{
            "id": m.id, "from_staff": m.from_staff, "body": m.body, "created_at": m.created_at,
            "author": m.author.full_name if for_staff or m.from_staff else "Вы",
        } for m in t.messages]
    return data
