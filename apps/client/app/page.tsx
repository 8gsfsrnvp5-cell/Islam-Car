import Link from "next/link";

import { CarCard } from "@/components/CarCard";
import { getCars } from "@/lib/server";

export default async function HomePage() {
  const cars = (await getCars()) ?? [];
  return (
    <>
      <section className="hero">
        <div className="container">
          <h1>Автомобиль с оплатой по графику — без процентов</h1>
          <p>
            Мы покупаем автомобиль в собственность и продаём его вам по окончательной цене, которая фиксируется в договоре.
            Цена не растёт из-за рассрочки или просрочки.
          </p>
          <div className="hero-actions">
            <Link href="/cars" className="btn btn-light">Смотреть каталог</Link>
            <Link href="/order" className="btn btn-ghost">Подобрать автомобиль под заказ</Link>
          </div>
          <div className="hero-facts">
            <div><strong>Фиксированная цена</strong><span>известна до подписания договора</span></div>
            <div><strong>Без процентов и штрафов</strong><span>за рассрочку и за просрочку</span></div>
            <div><strong>Личный кабинет</strong><span>график, платежи и остаток долга</span></div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <div className="section-head"><h2>Как проходит покупка</h2></div>
          <div className="steps">
            <div className="step"><b>1</b><h3>Выберите автомобиль</h3><p>В каталоге или оставьте запрос на автомобиль, которого у нас нет.</p></div>
            <div className="step"><b>2</b><h3>Оставьте заявку</h3><p>Имя и телефон. Паспортные данные на этом шаге не нужны.</p></div>
            <div className="step"><b>3</b><h3>Подпишите договор</h3><p>Цена, первоначальный взнос и график платежей фиксируются в договоре.</p></div>
            <div className="step"><b>4</b><h3>Платите по графику</h3><p>Каждый подтверждённый платёж сразу виден в личном кабинете.</p></div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <div className="section-head">
            <div><h2>Автомобили в каталоге</h2><p>Статус наличия показывает, оформлен ли автомобиль в нашу собственность</p></div>
            <Link href="/cars" className="btn btn-sm">Весь каталог</Link>
          </div>
          {cars.length ? (
            <div className="cars">{cars.slice(0, 6).map((c) => <CarCard key={c.id} car={c} />)}</div>
          ) : (
            <div className="panel">
              <p>Сейчас в каталоге нет опубликованных автомобилей.</p>
              <Link href="/order" className="btn btn-primary">Оставить запрос на подбор</Link>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
