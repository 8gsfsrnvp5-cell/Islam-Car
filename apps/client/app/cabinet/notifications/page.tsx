"use client";

import { type AppNotification, api, formatDateTime } from "@islamic-car/shared";
import Link from "next/link";
import { useEffect } from "react";

import { useClientApi } from "@/lib/useClientApi";

export default function NotificationsPage() {
  const { data } = useClientApi<AppNotification[]>("/api/client/notifications");

  useEffect(() => {
    // Открытие страницы = уведомления прочитаны
    if (data?.some((n) => !n.read)) api("/api/client/notifications/read-all", { method: "POST" }).catch(() => undefined);
  }, [data]);

  return (
    <>
      <h1>Уведомления</h1>
      <div className="panel">
        {!data ? <p>Загрузка…</p> : !data.length ? <p className="muted">Уведомлений пока нет.</p> : data.map((n) => (
          <div className="list-item" key={n.id}>
            <div>
              {n.link ? <Link href={n.link}>{n.read ? n.title : <strong>{n.title}</strong>}</Link> : n.title}
              {n.body ? <div className="small muted">{n.body}</div> : null}
            </div>
            <span className="small muted">{formatDateTime(n.created_at)}</span>
          </div>
        ))}
      </div>
    </>
  );
}
