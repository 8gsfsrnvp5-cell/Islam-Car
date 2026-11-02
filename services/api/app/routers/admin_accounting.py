"""Бухгалтерия и налоги: профиль, параметры правил, расчёты, журнал операций, налоговый календарь."""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import TaxCalendarEvent, TaxParam, User
from app.schemas import StrictModel
from app.security import Actor, require
from app.services import audit
from app.services.accounting import PARAMS, REGIMES, calculate, operations, parse_value
from app.services.common import today
from app.services.contracts import get_company

router = APIRouter(prefix="/api/admin/accounting", tags=["admin: accounting"])


class ProfileIn(StrictModel):
    tax_regime: str = Field(pattern=r"^(|individual_ndfl|usn_income|usn_income_expense|osno)$")
    vat_payer: bool = False


class ParamIn(StrictModel):
    code: str
    value: str = Field(min_length=1, max_length=40)
    effective_from: date
    effective_to: date | None = None
    source_url: str = Field(min_length=10, max_length=500, pattern=r"^https?://")
    note: str = Field(default="", max_length=2000)


class EventIn(StrictModel):
    title: str = Field(min_length=3, max_length=300)
    due_date: date
    knowledge_code: str = Field(default="", max_length=80)
    source_url: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=2000)


def profile_dict(db: Session) -> dict:
    co = get_company(db)
    return {"tax_regime": co.tax_regime, "vat_payer": co.vat_payer, "regimes": REGIMES,
            "seller_regime": co.seller_regime}


@router.get("/profile")
def get_profile(actor: Actor = Depends(require("accounting.read")), db: Session = Depends(get_db)):
    data = profile_dict(db)
    db.commit()
    return data


@router.put("/profile")
def save_profile(data: ProfileIn, actor: Actor = Depends(require("accounting.approve")), db: Session = Depends(get_db)):
    co = get_company(db)
    if data.tax_regime == "individual_ndfl" and co.seller_regime.value != "individual_one_off":
        raise HTTPException(422, "Режим «НДФЛ физлица» соответствует продавцу — физическому лицу (Настройки)")
    business = data.tax_regime in ("usn_income", "usn_income_expense", "osno")
    if business and co.seller_regime.value == "individual_one_off":
        raise HTTPException(422, "УСН и ОСНО применяются к ИП и организациям — проверьте режим продавца в Настройках")
    before = {"tax_regime": co.tax_regime, "vat_payer": co.vat_payer}
    co.tax_regime = data.tax_regime
    co.vat_payer = data.vat_payer
    audit.record(db, actor, "accounting.profile", "settings", "tax", before=before, after=data.model_dump())
    db.commit()
    return profile_dict(db)


def param_dict(p: TaxParam, names: dict) -> dict:
    d = PARAMS.get(p.code, {})
    return {"id": p.id, "code": p.code, "title": d.get("title", p.code), "unit": d.get("unit", ""), "value": p.value,
            "effective_from": p.effective_from, "effective_to": p.effective_to, "source_url": p.source_url,
            "note": p.note, "status": p.status, "knowledge_code": d.get("knowledge"),
            "entered_by": names.get(p.entered_by), "approved_by": names.get(p.approved_by),
            "approved_at": p.approved_at, "created_at": p.created_at}


@router.get("/params")
def list_params(actor: Actor = Depends(require("accounting.read")), db: Session = Depends(get_db)):
    names = dict(db.execute(select(User.id, User.full_name)).all())
    rows = db.scalars(select(TaxParam).order_by(TaxParam.code, TaxParam.effective_from.desc())).all()
    return {"definitions": PARAMS, "items": [param_dict(p, names) for p in rows]}


@router.post("/params", status_code=201)
def add_param(data: ParamIn, actor: Actor = Depends(require("accounting.write")), db: Session = Depends(get_db)):
    if data.code not in PARAMS:
        raise HTTPException(422, "Неизвестный параметр")
    try:
        parse_value(data.code, data.value)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if data.effective_to and data.effective_to < data.effective_from:
        raise HTTPException(422, "Дата окончания раньше даты начала")
    p = TaxParam(**data.model_dump(), entered_by=actor.user.id, status="draft")
    db.add(p)
    db.flush()
    audit.record(db, actor, "tax_param.entered", "tax_param", p.id, code=p.code, value=p.value,
                 effective_from=p.effective_from, source=p.source_url)
    db.commit()
    return param_dict(p, {actor.user.id: actor.user.full_name})


@router.post("/params/{param_id}/approve")
def approve_param(param_id: uuid.UUID, actor: Actor = Depends(require("accounting.approve")),
                  db: Session = Depends(get_db)):
    p = db.get(TaxParam, param_id)
    if not p or p.status != "draft":
        raise HTTPException(409, "Утвердить можно только черновик параметра")
    overlap = db.scalar(select(TaxParam.id).where(
        TaxParam.code == p.code, TaxParam.status == "approved", TaxParam.id != p.id,
        TaxParam.effective_from <= (p.effective_to or date.max),
        (TaxParam.effective_to.is_(None)) | (TaxParam.effective_to >= p.effective_from)))
    if overlap:
        raise HTTPException(409, "Есть утверждённое значение на пересекающийся период — сначала отзовите его или "
                                 "укажите дату окончания")
    p.status = "approved"
    p.approved_by = actor.user.id
    p.approved_at = datetime.now(UTC)
    audit.record(db, actor, "tax_param.approved", "tax_param", p.id, code=p.code, value=p.value)
    db.commit()
    return param_dict(p, dict(db.execute(select(User.id, User.full_name)).all()))


@router.post("/params/{param_id}/revoke")
def revoke_param(param_id: uuid.UUID, actor: Actor = Depends(require("accounting.approve")),
                 db: Session = Depends(get_db)):
    p = db.get(TaxParam, param_id)
    if not p or p.status == "revoked":
        raise HTTPException(409, "Параметр не найден или уже отозван")
    p.status = "revoked"
    audit.record(db, actor, "tax_param.revoked", "tax_param", p.id, code=p.code)
    db.commit()
    return param_dict(p, dict(db.execute(select(User.id, User.full_name)).all()))


@router.get("/calculate")
def run_calculation(date_from: date, date_to: date, actor: Actor = Depends(require("accounting.read")),
                    db: Session = Depends(get_db)):
    if date_to < date_from:
        raise HTTPException(422, "Конец периода раньше начала")
    return calculate(db, date_from, date_to)


@router.get("/operations")
def list_operations(date_from: date, date_to: date, actor: Actor = Depends(require("accounting.read")),
                    db: Session = Depends(get_db)):
    return operations(db, date_from, date_to)


def event_dict(e: TaxCalendarEvent) -> dict:
    return {"id": e.id, "title": e.title, "due_date": e.due_date, "knowledge_code": e.knowledge_code,
            "source_url": e.source_url, "note": e.note, "status": e.status, "done_at": e.done_at,
            "overdue": e.status == "open" and e.due_date < today()}


@router.get("/calendar")
def calendar(actor: Actor = Depends(require("accounting.read")), db: Session = Depends(get_db)):
    return [event_dict(e) for e in db.scalars(select(TaxCalendarEvent).order_by(TaxCalendarEvent.due_date))]


@router.post("/calendar", status_code=201)
def add_event(data: EventIn, actor: Actor = Depends(require("accounting.write")), db: Session = Depends(get_db)):
    e = TaxCalendarEvent(**data.model_dump(), created_by=actor.user.id)
    db.add(e)
    db.flush()
    audit.record(db, actor, "tax_calendar.added", "tax_calendar", e.id, title=e.title, due=e.due_date)
    db.commit()
    return event_dict(e)


@router.post("/calendar/{event_id}/done")
def event_done(event_id: uuid.UUID, actor: Actor = Depends(require("accounting.write")), db: Session = Depends(get_db)):
    e = db.get(TaxCalendarEvent, event_id)
    if not e or e.status != "open":
        raise HTTPException(409, "Событие не найдено или уже закрыто")
    e.status = "done"
    e.done_at = datetime.now(UTC)
    audit.record(db, actor, "tax_calendar.done", "tax_calendar", e.id)
    db.commit()
    return event_dict(e)
