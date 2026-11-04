"""Демонстрационные карточки автомобилей ДЛЯ ЛОКАЛЬНОЙ РАЗРАБОТКИ.

Запускается только при ENVIRONMENT=development и никогда в рабочей системе.
Все карточки помечены «ДЕМО», VIN начинаются с DEM и не принадлежат реальным машинам.
    python -m scripts.seed_demo
"""

import sys

from app.config import get_settings
from app.db import SessionLocal
from app.models import Car, CarStatus, OwnershipStatus

DEMO = [
    ("Toyota", "Camry", 2021, 45_000, OwnershipStatus.owned, 1_200_000, 1_600_000, "DEM00000000000001"),
    ("Hyundai", "Tucson", 2022, 30_000, OwnershipStatus.owned, 2_100_000, 2_650_000, "DEM00000000000002"),
    ("Kia", "K5", 2023, 12_000, OwnershipStatus.purchasing, 2_300_000, 2_900_000, None),
]


def main() -> int:
    if get_settings().environment != "development":
        print("Отказ: демо-данные создаются только при ENVIRONMENT=development", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        for make, model, year, km, own, cost, price, vin in DEMO:
            db.add(Car(make=make, model=model, year=year, mileage_km=km, ownership_status=own,
                       status=CarStatus.available, is_published=True, vin=vin,
                       purchase_price_kopecks=cost * 100, sale_price_kopecks=price * 100,
                       min_down_payment_kopecks=price * 25, max_term_months=24,
                       purchase_document="ДЕМО — не реальный документ" if own == OwnershipStatus.owned else "",
                       description="ДЕМО-карточка для локальной разработки. Не является предложением."))
        db.commit()
    print(f"Создано демо-карточек: {len(DEMO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
