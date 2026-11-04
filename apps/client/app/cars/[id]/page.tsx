import { AVAILABILITY, AVAILABILITY_HINT, formatRub, pluralMonths } from "@islamic-car/shared";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ApplicationForm } from "@/components/ApplicationForm";
import { Gallery } from "@/components/Gallery";
import { getCar } from "@/lib/server";

type Params = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const car = await getCar((await params).id);
  return { title: car ? `${car.make} ${car.model}, ${car.year}` : "Автомобиль не найден" };
}

export default async function CarPage({ params }: Params) {
  const car = await getCar((await params).id);
  if (!car) notFound();
  const title = `${car.make} ${car.model}, ${car.year}`;
  const specs: [string, string][] = [
    ["Год выпуска", String(car.year)],
    ["Пробег", `${car.mileage_km.toLocaleString("ru-RU")} км`],
    ["Двигатель", car.engine], ["Коробка передач", car.transmission], ["Привод", car.drive],
    ["Кузов", car.body_type], ["Цвет", car.color], ["VIN", car.vin_tail ? `•••• ${car.vin_tail.slice(-4)}` : ""],
  ];

  return (
    <div className="container">
      <p style={{ marginTop: 20 }}><Link href="/cars">← Каталог</Link></p>
      <h1>{title}</h1>
      <span className={`badge ${car.availability}`}>{AVAILABILITY[car.availability]}</span>
      <div className="detail">
        <div>
          <Gallery photos={car.photos} alt={title} />
          <div className="panel" style={{ marginTop: 18 }}>
            <h2>Характеристики</h2>
            <table className="specs"><tbody>
              {specs.filter(([, v]) => v).map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}
            </tbody></table>
          </div>
          {car.trim ? <div className="panel"><h2>Комплектация</h2><p style={{ whiteSpace: "pre-wrap" }}>{car.trim}</p></div> : null}
          {car.condition ? <div className="panel"><h2>Состояние</h2><p style={{ whiteSpace: "pre-wrap" }}>{car.condition}</p></div> : null}
          {car.description ? <div className="panel"><h2>Описание</h2><p style={{ whiteSpace: "pre-wrap" }}>{car.description}</p></div> : null}
        </div>
        <div>
          <div className="panel">
            <div className="muted small">Окончательная цена</div>
            <div className="price-big">{formatRub(car.sale_price_kopecks)}</div>
            <p className="small muted">Цена фиксируется в договоре. Проценты за рассрочку, пени и штрафы за просрочку не начисляются.</p>
            {car.min_down_payment_kopecks || car.max_term_months ? (
              <p className="small">
                {car.min_down_payment_kopecks ? <>Первоначальный взнос от {formatRub(car.min_down_payment_kopecks)}. </> : null}
                {car.max_term_months ? <>Срок до {pluralMonths(car.max_term_months)}.</> : null}
              </p>
            ) : null}
            <div className={`notice ${car.availability === "in_stock" ? "ok" : "warn"}`}>{AVAILABILITY_HINT[car.availability]}</div>
          </div>
          <div className="panel">
            <h2>Заявка на рассрочку</h2>
            <ApplicationForm kind="catalog" carId={car.id} price={car.sale_price_kopecks}
                             minDown={car.min_down_payment_kopecks} maxTerm={car.max_term_months} />
          </div>
        </div>
      </div>
    </div>
  );
}
