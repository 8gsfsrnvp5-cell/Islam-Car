import { AVAILABILITY, type PublicCar, formatRub, pluralMonths } from "@islamic-car/shared";
import Link from "next/link";

export function CarCard({ car }: { car: PublicCar }) {
  return (
    <Link href={`/cars/${car.id}`} className="car-card">
      <div className="car-photo">
        {car.photos[0] ? <img src={car.photos[0].url} alt={`${car.make} ${car.model}`} loading="lazy" /> : "Фото готовится"}
      </div>
      <div className="car-body">
        <div><span className={`badge ${car.availability}`}>{AVAILABILITY[car.availability]}</span></div>
        <div className="car-title">{car.make} {car.model}</div>
        <div className="car-meta">{car.year} · {car.mileage_km.toLocaleString("ru-RU")} км{car.engine ? ` · ${car.engine}` : ""}</div>
        <div className="car-price">{formatRub(car.sale_price_kopecks)}</div>
        <div className="car-terms">
          Окончательная цена без процентов
          {car.max_term_months ? ` · рассрочка до ${pluralMonths(car.max_term_months)}` : ""}
        </div>
      </div>
    </Link>
  );
}
