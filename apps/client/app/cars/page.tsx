import type { Metadata } from "next";
import Link from "next/link";

import { CarCard } from "@/components/CarCard";
import { getCars, getMakes } from "@/lib/server";

export const metadata: Metadata = { title: "Каталог автомобилей" };

type Search = { make?: string; q?: string; max_price?: string; availability?: string };

export default async function CatalogPage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const query = new URLSearchParams();
  if (sp.make) query.set("make", sp.make);
  if (sp.q) query.set("q", sp.q);
  if (sp.max_price && Number(sp.max_price) > 0) query.set("max_price_kopecks", String(Math.round(Number(sp.max_price) * 100)));
  if (sp.availability) query.set("availability", sp.availability);
  const [cars, makes] = await Promise.all([getCars(query.toString()), getMakes()]);

  return (
    <div className="container">
      <div className="section">
        <div className="section-head">
          <div><h1>Каталог автомобилей</h1><p>Окончательная цена указана сразу. Проценты за рассрочку не начисляются.</p></div>
        </div>
        <form className="filters" method="get">
          <label className="field"><span>Марка</span>
            <select name="make" defaultValue={sp.make ?? ""}>
              <option value="">Все марки</option>
              {(makes ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <label className="field"><span>Модель</span><input name="q" defaultValue={sp.q ?? ""} placeholder="например, Camry" /></label>
          <label className="field"><span>Цена до, ₽</span><input name="max_price" type="number" min={0} step={10000} defaultValue={sp.max_price ?? ""} /></label>
          <label className="field"><span>Наличие</span>
            <select name="availability" defaultValue={sp.availability ?? ""}>
              <option value="">Любое</option>
              <option value="in_stock">В наличии</option>
              <option value="purchasing">В процессе закупки</option>
            </select>
          </label>
          <button className="btn btn-primary">Показать</button>
        </form>
        {cars === null ? (
          <div className="notice danger">Каталог временно недоступен. Попробуйте обновить страницу позже.</div>
        ) : cars.length ? (
          <div className="cars">{cars.map((c) => <CarCard key={c.id} car={c} />)}</div>
        ) : (
          <div className="panel">
            <p>По вашему запросу автомобилей нет. Мы можем подобрать и купить автомобиль под ваш запрос.</p>
            <Link href="/order" className="btn btn-primary">Оставить запрос на подбор</Link>
          </div>
        )}
      </div>
    </div>
  );
}
