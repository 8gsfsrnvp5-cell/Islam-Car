"""Публичные маршруты: каталог, заявки, статус заявки. Без авторизации."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationKind,
    ApplicationStatus,
    Car,
    CarPhoto,
)
from app.schemas import ApplicationIn
from app.security import client_ip
from app.serializers import PUBLIC_CAR_STATUSES, application_public, car_public
from app.services.common import normalize_phone
from app.services.contracts import get_company
from app.services.files import photo_path
from app.services.notify import notify_staff, rub

router = APIRouter(prefix="/api/public", tags=["public"])

CONSENT_VERSION = "2026-11-draft"  # текст согласия требует утверждения юристом
MAX_APPLICATIONS_PER_IP_PER_HOUR = 10


def public_cars_query():
    return select(Car).where(Car.is_published.is_(True), Car.status.in_(PUBLIC_CAR_STATUSES))


@router.get("/cars")
def list_cars(q: str = "", make: str = "", max_price_kopecks: int | None = None,
              availability: str = "", db: Session = Depends(get_db)):
    stmt = public_cars_query().options(selectinload(Car.photos)).order_by(Car.created_at.desc())
    if make:
        stmt = stmt.where(func.lower(Car.make) == make.lower())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Car.make).like(like), func.lower(Car.model).like(like)))
    if max_price_kopecks:
        stmt = stmt.where(Car.sale_price_kopecks <= max_price_kopecks)
    cars = [car_public(c) for c in db.scalars(stmt).all()]
    if availability:
        cars = [c for c in cars if c["availability"] == availability]
    return cars


@router.get("/makes")
def list_makes(db: Session = Depends(get_db)):
    sub = public_cars_query().subquery()
    return sorted({m for m in db.scalars(select(sub.c.make).distinct()).all()})


@router.get("/cars/{car_id}")
def get_car(car_id: uuid.UUID, db: Session = Depends(get_db)):
    car = db.scalar(public_cars_query().where(Car.id == car_id).options(selectinload(Car.photos)))
    if not car:
        raise HTTPException(404, "Автомобиль не найден или снят с продажи")
    return car_public(car)


@router.get("/cars/{car_id}/photos/{photo_id}")
def get_photo(car_id: uuid.UUID, photo_id: uuid.UUID, db: Session = Depends(get_db)):
    car = db.scalar(public_cars_query().where(Car.id == car_id))
    photo = db.get(CarPhoto, photo_id)
    if not car or not photo or photo.car_id != car.id:
        raise HTTPException(404, "Фото не найдено")
    return FileResponse(photo_path(photo.file_name), media_type=photo.content_type,
                        headers={"Cache-Control": "public, max-age=3600"})


@router.get("/company")
def company_info(db: Session = Depends(get_db)):
    c = get_company(db)
    return {"seller_name": c.seller_name, "support_phone": c.support_phone, "consent_version": CONSENT_VERSION}


@router.post("/applications", status_code=201)
def create_application(data: ApplicationIn, request: Request, db: Session = Depends(get_db)):
    if data.website:
        raise HTTPException(400, "Заявка отклонена")
    if not data.consent_personal_data:
        raise HTTPException(422, "Нужно согласие на обработку персональных данных")
    phone = normalize_phone(data.phone)

    ip = client_ip(request)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest() if ip else None
    if ip_hash:
        recent = db.scalar(select(func.count()).select_from(Application).where(
            Application.source_ip_hash == ip_hash,
            Application.created_at >= datetime.now(UTC) - timedelta(hours=1)))
        if recent >= MAX_APPLICATIONS_PER_IP_PER_HOUR:
            raise HTTPException(429, "Слишком много заявок. Попробуйте позже или позвоните нам.")

    car = None
    if data.kind == ApplicationKind.catalog:
        if not data.car_id:
            raise HTTPException(422, "Выберите автомобиль")
        car = db.scalar(public_cars_query().where(Car.id == data.car_id))
        if not car:
            raise HTTPException(404, "Автомобиль не найден или снят с продажи")
    elif not (data.wanted_make and data.wanted_model):
        raise HTTPException(422, "Укажите марку и модель автомобиля")

    app_ = Application(
        public_token=secrets.token_urlsafe(18), kind=data.kind, car_id=car.id if car else None,
        name=data.name, phone=phone, desired_down_payment_kopecks=data.desired_down_payment_kopecks,
        desired_term_months=data.desired_term_months, comment=data.comment,
        wanted_make=data.wanted_make, wanted_model=data.wanted_model, wanted_year=data.wanted_year,
        wanted_trim=data.wanted_trim, max_budget_kopecks=data.max_budget_kopecks,
        consent_personal_data=True, consent_version=CONSENT_VERSION, source_ip_hash=ip_hash,
        public_message="Заявка получена. Менеджер свяжется с вами.",
    )
    db.add(app_)
    db.flush()
    db.add(ApplicationEvent(application_id=app_.id, from_status=None, to_status=ApplicationStatus.new.value,
                            public_message=app_.public_message))
    if car:
        title = f"Новая заявка: {car.make} {car.model}, {car.year}"
        body = f"{data.name}, {phone}. Цена {rub(car.sale_price_kopecks)}."
    else:
        title = f"Заказ автомобиля: {data.wanted_make} {data.wanted_model}"
        body = f"{data.name}, {phone}."
        if data.max_budget_kopecks:
            body += f" Бюджет до {rub(data.max_budget_kopecks)}."
    notify_staff(db, "application.new", title, body, f"/applications/{app_.id}")
    db.commit()
    return {"public_token": app_.public_token, "status": app_.status}


@router.get("/applications/{token}")
def application_status(token: str, db: Session = Depends(get_db)):
    app_ = db.scalar(select(Application).where(Application.public_token == token))
    if not app_:
        raise HTTPException(404, "Заявка не найдена")
    return application_public(app_)


@router.post("/applications/{token}/withdraw")
def withdraw_application(token: str, db: Session = Depends(get_db)):
    app_ = db.scalar(select(Application).where(Application.public_token == token))
    if not app_:
        raise HTTPException(404, "Заявка не найдена")
    if app_.status in (ApplicationStatus.converted, ApplicationStatus.rejected, ApplicationStatus.withdrawn):
        raise HTTPException(409, "Эту заявку уже нельзя отозвать")
    db.add(ApplicationEvent(application_id=app_.id, from_status=app_.status.value,
                            to_status=ApplicationStatus.withdrawn.value, public_message="Заявка отозвана вами"))
    app_.status = ApplicationStatus.withdrawn
    app_.public_message = "Заявка отозвана вами"
    notify_staff(db, "application.withdrawn", f"Клиент отозвал заявку: {app_.name}", "",
                 f"/applications/{app_.id}")
    db.commit()
    return application_public(app_)
