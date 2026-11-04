"""Проверочный лист автомобиля до покупки и проверка договора на принципы мурабахи."""

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Car, CarCheck, Contract
from app.security import Actor, require
from app.services import audit, car_checks, murabaha

router = APIRouter(prefix="/api/admin", tags=["admin: checks"])

EVIDENCE_TYPES = {b"%PDF": ("application/pdf", ".pdf"), b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
                  b"\x89PNG\r\n\x1a\n": ("image/png", ".png")}


def evidence_dir():
    d = get_settings().storage_dir / "car-checks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_car(db: Session, car_id: uuid.UUID) -> Car:
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Автомобиль не найден")
    return car


@router.get("/cars/{car_id}/checks")
def car_check_list(car_id: uuid.UUID, actor: Actor = Depends(require("cars.read")), db: Session = Depends(get_db)):
    car = get_car(db, car_id)
    history = db.scalars(select(CarCheck).where(CarCheck.car_id == car.id).order_by(CarCheck.checked_at.desc())).all()
    return {**car_checks.summary(db, car), "statuses": car_checks.STATUSES,
            "history": [{"item_code": h.item_code, "status": h.status, "source": h.source, "reference": h.reference,
                         "checked_at": h.checked_at} for h in history[:50]]}


@router.post("/cars/{car_id}/checks", status_code=201)
async def record_check(car_id: uuid.UUID, item_code: str = Form(...), status: str = Form(...),
                       source: str = Form(...), reference: str = Form(""), notes: str = Form(""),
                       file: UploadFile | None = File(None), actor: Actor = Depends(require("cars.write")),
                       db: Session = Depends(get_db)):
    """Сотрудник вносит результат пункта проверки по законному источнику (с подтверждением по возможности)."""
    car = get_car(db, car_id)
    if item_code not in car_checks.ITEM_CODES:
        raise HTTPException(422, "Неизвестный пункт проверки")
    if status not in car_checks.STATUSES:
        raise HTTPException(422, "Неизвестный статус")
    if status in ("ok", "problem") and len(source.strip()) < 3:
        raise HTTPException(422, "Укажите источник сведений")
    row = CarCheck(car_id=car.id, item_code=item_code, status=status, source=source.strip()[:200],
                   reference=reference.strip()[:300], notes=notes.strip(), checked_by=actor.user.id)
    if file is not None and file.filename:
        content = await file.read(get_settings().max_document_bytes + 1)
        if len(content) > get_settings().max_document_bytes:
            raise HTTPException(413, "Файл слишком большой")
        kind = next((v for sig, v in EVIDENCE_TYPES.items() if content.startswith(sig)), None)
        if not kind:
            raise HTTPException(415, "Подтверждение — PDF, JPEG или PNG")
        name = f"{uuid.uuid4().hex}{kind[1]}"
        (evidence_dir() / name).write_bytes(content)
        row.evidence_file, row.evidence_type = name, kind[0]
        row.evidence_sha256 = hashlib.sha256(content).hexdigest()
    db.add(row)
    audit.record(db, actor, "car.check", "car", car.id, item=item_code, status=status, source=source)
    db.commit()
    return car_check_list(car_id, actor, db)


@router.get("/cars/{car_id}/checks/{check_id}/evidence")
def evidence(car_id: uuid.UUID, check_id: uuid.UUID, actor: Actor = Depends(require("cars.read")),
             db: Session = Depends(get_db)):
    row = db.get(CarCheck, check_id)
    if not row or row.car_id != car_id or not row.evidence_file:
        raise HTTPException(404, "Подтверждение не найдено")
    return FileResponse(evidence_dir() / row.evidence_file, media_type=row.evidence_type)


@router.get("/contracts/{contract_id}/murabaha")
def murabaha_check(contract_id: uuid.UUID, actor: Actor = Depends(require("contracts.read")),
                   db: Session = Depends(get_db)):
    c = db.get(Contract, contract_id)
    if not c:
        raise HTTPException(404, "Договор не найден")
    return murabaha.evaluate(db, c)
