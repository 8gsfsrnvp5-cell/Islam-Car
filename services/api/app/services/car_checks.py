"""Проверочный лист автомобиля до покупки.

Результаты вносит сотрудник по данным законных источников и прикладывает подтверждение. Система и агенты
результаты проверок не придумывают: агент только составляет список пунктов и находит противоречия.
Автоматические подключения к источникам — после официальных договоров и доступов (в планах, см. docs/roadmap.md).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Car, CarCheck

ITEMS: list[dict] = [
    {"code": "vin_match", "title": "VIN на кузове, в ПТС/ЭПТС и в карточке совпадают", "required": True,
     "sources": ["Осмотр автомобиля и документов"]},
    {"code": "title_documents", "title": "ПТС/ЭПТС и СТС в порядке, продавец вправе продать автомобиль",
     "required": True,
     "sources": ["Документы продавца", "Электронный паспорт (ЭПТС)"]},
    {"code": "seller_identity", "title": "Продавец — собственник или уполномоченное лицо", "required": True,
     "sources": ["Паспорт и документы продавца", "Доверенность"]},
    {"code": "gibdd_registration", "title": "История регистрации", "required": True,
     "sources": ["Госавтоинспекция: сервис проверки автомобиля"]},
    {"code": "gibdd_wanted", "title": "Автомобиль не в розыске", "required": True,
     "sources": ["Госавтоинспекция: сервис проверки автомобиля"]},
    {"code": "gibdd_restrictions", "title": "Нет ограничений на регистрационные действия", "required": True,
     "sources": ["Госавтоинспекция: сервис проверки автомобиля"]},
    {"code": "pledge_registry", "title": "Нет сведений о залоге", "required": True,
     "sources": ["Реестр уведомлений о залоге движимого имущества (Федеральная нотариальная палата)"]},
    {"code": "accidents", "title": "Сведения о ДТП", "required": False,
     "sources": ["Госавтоинспекция: сервис проверки автомобиля"]},
    {"code": "mileage", "title": "Пробег подтверждается историей обслуживания и техосмотров", "required": False,
     "sources": ["Сервисная книжка", "Диагностические карты", "Документы дилера"]},
    {"code": "technical", "title": "Техническое состояние проверено", "required": False,
     "sources": ["Акт диагностики СТО"]},
]
ITEM_CODES = {i["code"] for i in ITEMS}
STATUSES = {"ok": "Проверено, замечаний нет", "problem": "Есть проблема", "not_applicable": "Не применимо",
            "not_checked": "Не проверено"}


def latest(db: Session, car_id: uuid.UUID) -> dict[str, CarCheck]:
    result: dict[str, CarCheck] = {}
    for row in db.scalars(select(CarCheck).where(CarCheck.car_id == car_id).order_by(CarCheck.checked_at)):
        result[row.item_code] = row
    return result


def summary(db: Session, car: Car) -> dict:
    current = latest(db, car.id)
    items = []
    for item in ITEMS:
        row = current.get(item["code"])
        items.append({**item, "status": row.status if row else "not_checked",
                      "source": row.source if row else "", "reference": row.reference if row else "",
                      "notes": row.notes if row else "", "checked_at": row.checked_at if row else None,
                      "has_evidence": bool(row and row.evidence_file), "check_id": row.id if row else None})
    problems = [i for i in items if i["status"] == "problem"]
    missing = [i for i in items if i["required"] and i["status"] == "not_checked"]
    if problems:
        verdict, tone = "Найдены проблемы — покупку не проводить до их устранения", "problem"
    elif missing:
        verdict, tone = f"Не завершено: осталось обязательных пунктов — {len(missing)}", "incomplete"
    else:
        verdict, tone = "Обязательные пункты проверены, проблем не найдено", "ok"
    return {"items": items, "verdict": verdict, "state": tone, "problems": len(problems),
            "missing_required": len(missing)}
