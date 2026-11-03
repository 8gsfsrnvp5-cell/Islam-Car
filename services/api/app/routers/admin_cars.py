import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import AuditLog, Car, CarPhoto, CarStatus, OwnershipStatus
from app.schemas import CarIn, CarPatch, StrictModel
from app.security import Actor, require
from app.serializers import car_staff
from app.services import audit, car_recognition
from app.services.common import normalize_vin
from app.services.files import photo_path, read_photo, save_photo

router = APIRouter(prefix="/api/admin/cars", tags=["admin: cars"])

MAX_PHOTOS = 20
MAX_RECOGNITIONS_PER_HOUR = 60


class RecognitionSettingsIn(StrictModel):
    enabled: bool
    confirm_data_scope: bool = False


def get_car(db: Session, car_id: uuid.UUID) -> Car:
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Автомобиль не найден")
    return car


def validate_car(car: Car) -> None:
    if car.status == CarStatus.sold:
        return
    if car.ownership_status == OwnershipStatus.owned and not car.vin:
        raise HTTPException(422, "Для автомобиля в собственности обязателен VIN")
    if car.min_down_payment_kopecks is not None and car.min_down_payment_kopecks >= car.sale_price_kopecks:
        raise HTTPException(422, "Минимальный взнос должен быть меньше цены")


def check_publishable(car: Car) -> None:
    problems = []
    if car.status not in (CarStatus.available, CarStatus.reserved):
        problems.append("статус должен быть «В продаже» или «Забронирован»")
    if not car.sale_price_kopecks:
        problems.append("не указана цена продажи")
    if car.ownership_status == OwnershipStatus.owned and not car.vin:
        problems.append("не указан VIN")
    if problems:
        raise HTTPException(422, "Нельзя опубликовать: " + "; ".join(problems))


def recognition_dict(db: Session, actor: Actor) -> dict:
    st = car_recognition.status(db)
    return {"enabled": st.enabled, "configured": st.configured, "model": st.model, "reason": st.reason,
            "changed_at": st.changed_at, "can_manage": actor.can("settings.write"),
            "data_scope": car_recognition.DATA_SCOPE, "disclaimer": car_recognition.DISCLAIMER}


# Маршруты распознавания объявлены до /{car_id}, чтобы «recognition» не принималось за идентификатор
@router.get("/recognition")
def recognition_status(actor: Actor = Depends(require("cars.read")), db: Session = Depends(get_db)):
    return recognition_dict(db, actor)


@router.put("/recognition/settings")
def recognition_settings(data: RecognitionSettingsIn, actor: Actor = Depends(require("settings.write")),
                         db: Session = Depends(get_db)):
    """Включает распознавание по фото. Включение — только с подтверждением состава передаваемых данных."""
    if data.enabled and not data.confirm_data_scope:
        raise HTTPException(422, "Подтвердите, какие данные передаются во внешний сервис")
    car_recognition.set_enabled(db, data.enabled, str(actor.user.id))
    audit.record(db, actor, "car_recognition.enabled" if data.enabled else "car_recognition.disabled", "settings", 1,
                 data_scope=car_recognition.DATA_SCOPE if data.enabled else None)
    db.commit()
    return recognition_dict(db, actor)


@router.post("/recognize")
async def recognize(file: UploadFile = File(...), actor: Actor = Depends(require("cars.write")),
                    db: Session = Depends(get_db)):
    """Подсказка для карточки по фото. Ничего не сохраняет: поля проверяет и сохраняет сотрудник."""
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    recent = db.scalar(select(func.count(AuditLog.id)).where(
        AuditLog.actor_user_id == actor.user.id, AuditLog.action == "car.recognized",
        AuditLog.created_at >= hour_ago)) or 0
    if recent >= MAX_RECOGNITIONS_PER_HOUR:
        raise HTTPException(429, "Слишком много распознаваний за час — попробуйте позже")
    content = await read_photo(file)
    # Запрос к Claude идёт несколько секунд — в отдельном потоке, чтобы не задерживать другие запросы
    result = await run_in_threadpool(car_recognition.recognize, db, content)
    # В журнал — только вывод, без фотографии
    audit.record(db, actor, "car.recognized", "car", None, make=result["fields"].get("make"),
                 model=result["fields"].get("model"), confidence=result["confidence"])
    db.commit()
    return result


@router.get("")
def list_cars(q: str = "", status: CarStatus | None = None, ownership: OwnershipStatus | None = None,
              published: bool | None = None, actor: Actor = Depends(require("cars.read")),
              db: Session = Depends(get_db)):
    stmt = select(Car).options(selectinload(Car.photos)).order_by(Car.created_at.desc())
    if status:
        stmt = stmt.where(Car.status == status)
    if ownership:
        stmt = stmt.where(Car.ownership_status == ownership)
    if published is not None:
        stmt = stmt.where(Car.is_published.is_(published))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Car.make).like(like), func.lower(Car.model).like(like),
                              func.lower(Car.vin).like(like)))
    return [car_staff(c, actor) for c in db.scalars(stmt).all()]


@router.post("", status_code=201)
def create_car(data: CarIn, actor: Actor = Depends(require("cars.write")), db: Session = Depends(get_db)):
    values = data.model_dump()
    values["vin"] = normalize_vin(values["vin"])
    if not actor.can("cars.cost"):
        values.pop("purchase_price_kopecks")
    if values["status"] == CarStatus.sold:
        raise HTTPException(422, "Статус «Продан» устанавливается только подписанием договора")
    car = Car(**values, created_by=actor.user.id)
    validate_car(car)
    db.add(car)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Автомобиль с таким VIN уже есть в реестре") from None
    audit.record(db, actor, "car.created", "car", car.id, make=car.make, model=car.model, vin=car.vin)
    db.commit()
    db.refresh(car)
    return car_staff(car, actor)


@router.get("/{car_id}")
def read_car(car_id: uuid.UUID, actor: Actor = Depends(require("cars.read")), db: Session = Depends(get_db)):
    return car_staff(get_car(db, car_id), actor)


@router.patch("/{car_id}")
def update_car(car_id: uuid.UUID, data: CarPatch, actor: Actor = Depends(require("cars.write")),
               db: Session = Depends(get_db)):
    car = get_car(db, car_id)
    changes = data.model_dump(exclude_unset=True)
    if "vin" in changes:
        changes["vin"] = normalize_vin(changes["vin"])
    if "purchase_price_kopecks" in changes and not actor.can("cars.cost"):
        raise HTTPException(403, "Недостаточно прав для изменения закупочной стоимости")
    if car.status == CarStatus.sold:
        locked = {"vin", "sale_price_kopecks", "purchase_price_kopecks", "status", "ownership_status"}
        if locked & changes.keys():
            raise HTTPException(409, "Автомобиль продан по договору: ключевые данные изменить нельзя")
    if changes.get("status") == CarStatus.sold:
        raise HTTPException(422, "Статус «Продан» устанавливается только подписанием договора")
    before = {k: getattr(car, k) for k in changes}
    for key, value in changes.items():
        setattr(car, key, value)
    validate_car(car)
    if car.is_published and car.status not in (CarStatus.available, CarStatus.reserved):
        car.is_published = False
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Автомобиль с таким VIN уже есть в реестре") from None
    audit.record(db, actor, "car.updated", "car", car.id, before=before, after=changes)
    db.commit()
    return car_staff(car, actor)


@router.post("/{car_id}/publish")
def publish(car_id: uuid.UUID, actor: Actor = Depends(require("cars.write")), db: Session = Depends(get_db)):
    car = get_car(db, car_id)
    check_publishable(car)
    car.is_published = True
    audit.record(db, actor, "car.published", "car", car.id)
    db.commit()
    return car_staff(car, actor)


@router.post("/{car_id}/unpublish")
def unpublish(car_id: uuid.UUID, actor: Actor = Depends(require("cars.write")), db: Session = Depends(get_db)):
    car = get_car(db, car_id)
    car.is_published = False
    audit.record(db, actor, "car.unpublished", "car", car.id)
    db.commit()
    return car_staff(car, actor)


@router.post("/{car_id}/photos", status_code=201)
async def upload_photo(car_id: uuid.UUID, file: UploadFile = File(...), actor: Actor = Depends(require("cars.write")),
                       db: Session = Depends(get_db)):
    car = get_car(db, car_id)
    if len(car.photos) >= MAX_PHOTOS:
        raise HTTPException(409, f"Не больше {MAX_PHOTOS} фотографий")
    name, content_type = await save_photo(file)
    position = max((p.position for p in car.photos), default=-1) + 1
    car.photos.append(CarPhoto(file_name=name, content_type=content_type, position=position))
    audit.record(db, actor, "car.photo_added", "car", car.id)
    db.commit()
    db.refresh(car)
    return car_staff(car, actor)


@router.post("/{car_id}/photos/{photo_id}/main")
def make_main_photo(car_id: uuid.UUID, photo_id: uuid.UUID, actor: Actor = Depends(require("cars.write")),
                    db: Session = Depends(get_db)):
    """Главное фото показывается первым в каталоге и в списке автомобилей."""
    car = get_car(db, car_id)
    photo = next((p for p in car.photos if p.id == photo_id), None)
    if not photo:
        raise HTTPException(404, "Фото не найдено")
    for position, p in enumerate([photo, *(p for p in car.photos if p.id != photo_id)]):
        p.position = position
    audit.record(db, actor, "car.photo_main", "car", car.id)
    db.commit()
    db.refresh(car, ["photos"])  # перечитываем список в новом порядке
    return car_staff(car, actor)


@router.get("/{car_id}/photos/{photo_id}")
def staff_photo(car_id: uuid.UUID, photo_id: uuid.UUID, actor: Actor = Depends(require("cars.read")),
                db: Session = Depends(get_db)):
    photo = db.get(CarPhoto, photo_id)
    if not photo or photo.car_id != car_id:
        raise HTTPException(404, "Фото не найдено")
    return FileResponse(photo_path(photo.file_name), media_type=photo.content_type)


@router.delete("/{car_id}/photos/{photo_id}")
def delete_photo(car_id: uuid.UUID, photo_id: uuid.UUID, actor: Actor = Depends(require("cars.write")),
                 db: Session = Depends(get_db)):
    car = get_car(db, car_id)
    photo = next((p for p in car.photos if p.id == photo_id), None)
    if not photo:
        raise HTTPException(404, "Фото не найдено")
    car.photos.remove(photo)
    audit.record(db, actor, "car.photo_removed", "car", car.id, file=photo.file_name)
    db.commit()
    db.refresh(car)
    return car_staff(car, actor)
