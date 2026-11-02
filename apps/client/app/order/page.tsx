import type { Metadata } from "next";

import { ApplicationForm } from "@/components/ApplicationForm";

export const metadata: Metadata = { title: "Автомобиль под заказ" };

export default function OrderPage() {
  return (
    <div className="container">
      <div className="detail">
        <div>
          <h1>Автомобиль под заказ</h1>
          <p>Если нужного автомобиля нет в каталоге, опишите его. Мы подберём варианты и предложим конкретный автомобиль.</p>
          <div className="panel">
            <h2>Как это устроено</h2>
            <ol>
              <li>Вы описываете автомобиль, бюджет и желаемые условия.</li>
              <li>Менеджер предлагает подходящие варианты и окончательную цену.</li>
              <li>После вашего согласия мы покупаем автомобиль в свою собственность.</li>
              <li>Только после этого заключается договор купли-продажи с графиком платежей.</li>
            </ol>
            <p className="small muted">
              Пока автомобиль не куплен продавцом, договор купли-продажи не заключается: продать можно только то, чем продавец владеет.
            </p>
          </div>
        </div>
        <div className="panel">
          <h2>Запрос на подбор</h2>
          <ApplicationForm kind="custom_order" />
        </div>
      </div>
    </div>
  );
}
