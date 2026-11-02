"use client";

import { ROLE, api, label } from "@islamic-car/shared";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { useApi } from "@/lib/useApi";

export type Me = {
  id: string; login: string; full_name: string; role: string; totp_enabled: boolean; permissions: string[];
  two_factor_required?: boolean;
};

const MeContext = createContext<Me | null>(null);

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe вне Shell");
  return me;
}

export function useCan(permission: string): boolean {
  return useMe().permissions.includes(permission);
}

type NavItem = { href: string; title: string; soon?: number; badge?: "notifications" };

const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Операции", items: [
    { href: "/", title: "Операционный центр" },
    { href: "/applications", title: "Заявки клиентов" },
    { href: "/clients", title: "Реестр клиентов" },
    { href: "/cars", title: "Реестр автомобилей" },
    { href: "/contracts", title: "Договоры" },
    { href: "/payments", title: "Рассрочки и платежи" },
    { href: "/calendar", title: "Календарь поступлений" },
    { href: "/support", title: "Обращения клиентов" },
    { href: "/tasks", title: "Задачи и сроки" },
  ] },
  { group: "Контроль", items: [
    { href: "/documents", title: "Документы и шаблоны" },
    { href: "/collateral", title: "Залоги и страхование" },
    { href: "/finance", title: "Финансы" },
    { href: "/accounting", title: "Бухгалтерия и налоги" },
    { href: "/notifications", title: "Центр уведомлений", badge: "notifications" },
    { href: "/reports", title: "Отчёты" },
  ] },
  { group: "Знания и ИИ", items: [
    { href: "/knowledge", title: "Библиотеки знаний" },
    { href: "/agents", title: "Центр ИИ-агентов" },
  ] },
  { group: "Система", items: [{ href: "/settings", title: "Пользователи и настройки" }] },
];

type Unread = { unread: number; latest_id: string | null; latest_title: string | null };

export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useApi<Me>("/api/auth/admin/me");
  const unread = useApi<Unread>(me.data ? "/api/admin/notifications/unread-count" : null, 5000);
  const [toast, setToast] = useState<string | null>(null);
  const lastSeen = useRef<string | null | undefined>(undefined);
  const [query, setQuery] = useState("");

  // Всплывающее сообщение, когда приходит новое уведомление (например, новая заявка)
  useEffect(() => {
    if (!unread.data) return;
    if (lastSeen.current !== undefined && unread.data.latest_id && unread.data.latest_id !== lastSeen.current) {
      setToast(unread.data.latest_title);
      const id = setTimeout(() => setToast(null), 7000);
      lastSeen.current = unread.data.latest_id;
      return () => clearTimeout(id);
    }
    lastSeen.current = unread.data.latest_id;
  }, [unread.data]);

  if (me.loading || !me.data) {
    return <div className="login-wrap"><div className="login">Загрузка…</div></div>;
  }

  async function logout() {
    await api("/api/auth/admin/logout", { method: "POST" });
    router.replace("/login");
  }

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  // Владелец без второго фактора (если он обязателен) может только настроить его
  const needs2fa = Boolean(me.data.two_factor_required && !me.data.totp_enabled);

  return (
    <MeContext.Provider value={me.data}>
      <div className="layout">
        <aside className="side">
          <div className="brand">
            <div className="brand-mark">IC</div>
            <div>Islamic Car<small>Администрирование</small></div>
          </div>
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="nav-group">{g.group}</div>
              <nav className="nav">
                {g.items.map((it) => (
                  <Link key={it.href} href={it.href} className={isActive(it.href) ? "active" : ""}>
                    <span>{it.title}</span>
                    {it.soon ? <span className="soon">v{it.soon}</span> : null}
                    {it.badge === "notifications" && unread.data?.unread ? <span className="count">{unread.data.unread}</span> : null}
                  </Link>
                ))}
              </nav>
            </div>
          ))}
        </aside>
        <div className="main">
          <header className="topbar">
            <form onSubmit={(e) => { e.preventDefault(); if (query.trim()) router.push(`/search?q=${encodeURIComponent(query.trim())}`); }}>
              <input type="search" placeholder="Поиск: ФИО, телефон, VIN, номер договора, автомобиль" value={query}
                     onChange={(e) => setQuery(e.target.value)} aria-label="Глобальный поиск" />
            </form>
            <div className="spacer" />
            <Link className="bell" href="/notifications" title="Уведомления">
              Уведомления{unread.data?.unread ? <b>{unread.data.unread}</b> : null}
            </Link>
            <div className="user">
              {me.data.full_name}<br /><span>{label(ROLE, me.data.role)}</span>
            </div>
            <button className="btn btn-sm" onClick={logout}>Выйти</button>
          </header>
          <main className="content">
            {needs2fa ? (
              <div className="notice warn">
                <strong>Включите второй фактор входа</strong>
                Для владельца он обязателен. Остальные разделы откроются после настройки приложения-аутентификатора.{" "}
                {pathname !== "/settings" ? <Link href="/settings">Перейти к настройке</Link> : null}
              </div>
            ) : null}
            {needs2fa && pathname !== "/settings" ? null : children}
          </main>
        </div>
      </div>
      {toast ? (
        <div className="toast" role="status">
          <div><strong>Новое уведомление</strong></div>
          <div>{toast}</div>
          <Link href="/notifications" onClick={() => setToast(null)}>Открыть</Link>
        </div>
      ) : null}
    </MeContext.Provider>
  );
}
