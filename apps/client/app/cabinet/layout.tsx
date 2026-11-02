"use client";

import { type AppNotification, api } from "@islamic-car/shared";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { useClientApi } from "@/lib/useClientApi";

type Me = { full_name: string; phone: string; login: string };

export default function CabinetLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const me = useClientApi<Me>("/api/auth/client/me");
  const notes = useClientApi<AppNotification[]>(me.data ? "/api/client/notifications" : null, 20000);
  const unread = notes.data?.filter((n) => !n.read).length ?? 0;

  if (!me.data) return <div className="container"><p style={{ marginTop: 32 }}>{me.error ?? "Загрузка…"}</p></div>;

  async function logout() {
    await api("/api/auth/client/logout", { method: "POST" });
    router.replace("/login");
  }

  const link = (href: string, title: string, extra?: ReactNode) => (
    <Link href={href} className={(href === "/cabinet" ? pathname === href : pathname.startsWith(href)) ? "active" : ""}>
      <span>{title}</span>{extra}
    </Link>
  );

  return (
    <div className="container">
      <div className="cabinet">
        <aside className="cab-nav">
          <div style={{ padding: "8px 12px 12px" }}>
            <strong>{me.data.full_name}</strong>
            <div className="small muted">{me.data.phone}</div>
          </div>
          {link("/cabinet", "Мои договоры")}
          {link("/cabinet/documents", "Документы")}
          {link("/cabinet/payment", "Как оплатить")}
          {link("/cabinet/support", "Обращения")}
          {link("/cabinet/notifications", "Уведомления", unread ? <span className="count">{unread}</span> : null)}
          <hr />
          <a href="#" onClick={(e) => { e.preventDefault(); logout(); }}>Выйти</a>
        </aside>
        <main>{children}</main>
      </div>
    </div>
  );
}
