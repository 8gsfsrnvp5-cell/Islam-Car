import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { HeaderNav } from "@/components/HeaderNav";
import { getCompany } from "@/lib/server";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Islamic Car — автомобили в рассрочку без процентов", template: "%s · Islamic Car" },
  description: "Продажа автомобилей с оплатой по графику: окончательная цена фиксируется в договоре, без процентов за рассрочку и штрафов за просрочку.",
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const company = await getCompany();
  return (
    <html lang="ru">
      <body>
        <header className="header">
          <div className="container header-inner">
            <Link href="/" className="logo"><span className="logo-mark">IC</span>Islamic Car</Link>
            <HeaderNav />
            <Link href="/cabinet" className="btn btn-sm">Личный кабинет</Link>
          </div>
        </header>
        {children}
        <footer className="footer">
          <div className="container footer-grid">
            <div>
              <strong>Islamic Car</strong>
              <p>Продажа автомобилей с оплатой по графику. Продавец покупает автомобиль в собственность и продаёт его
                по заранее согласованной окончательной цене.</p>
              {company?.seller_name ? <small>Продавец: {company.seller_name}</small> : null}
            </div>
            <div>
              <div><Link href="/cars">Каталог</Link></div>
              <div><Link href="/order">Автомобиль под заказ</Link></div>
              <div><Link href="/how-it-works">Как это работает</Link></div>
            </div>
            <div>
              {company?.support_phone ? <div>Телефон: <a href={`tel:${company.support_phone}`}>{company.support_phone}</a></div> : null}
              <div><Link href="/privacy">Обработка персональных данных</Link></div>
              <small>Информация на сайте не является публичной офертой. Условия определяются договором.</small>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
