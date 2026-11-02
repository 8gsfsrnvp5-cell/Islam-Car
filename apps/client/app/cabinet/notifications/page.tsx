"use client";

import { type AppNotification, api, formatDateTime } from "@islamic-car/shared";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useClientApi } from "@/lib/useClientApi";

type Channels = { channels: { channel: string; address: string; verified: boolean; granted: boolean }[] };

function ChannelsPanel() {
  const { data, setData } = useClientApi<Channels>("/api/client/communications");
  const [error, setError] = useState<string | null>(null);
  async function toggle(channel: string, granted: boolean) {
    try {
      setData(await api<Channels>("/api/client/communications", { method: "POST", json: { channel, granted } }));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  }
  if (!data) return null;
  return (
    <div className="panel">
      <h2>Каналы напоминаний</h2>
      <p className="small muted">Уведомления в личном кабинете приходят всегда. SMS и письма о платежах — только с вашего согласия
        и только на номер или адрес, подтверждённый менеджером. Рекламу мы не присылаем.</p>
      {error ? <div className="form-error">{error}</div> : null}
      {data.channels.map((c) => (
        <div className="list-item" key={c.channel}>
          <div>
            <strong>{c.channel === "sms" ? "SMS" : "Электронная почта"}</strong>
            <div className="small muted">{c.address || "не указан"} · {c.verified ? "подтверждён" : "не подтверждён менеджером"}</div>
          </div>
          <label className="check"><input type="checkbox" checked={c.granted} onChange={(e) => toggle(c.channel, e.target.checked)} />
            <span>{c.granted ? "Согласие дано" : "Нет согласия"}</span></label>
        </div>
      ))}
    </div>
  );
}

export default function NotificationsPage() {
  const { data } = useClientApi<AppNotification[]>("/api/client/notifications");

  useEffect(() => {
    // Открытие страницы = уведомления прочитаны
    if (data?.some((n) => !n.read)) api("/api/client/notifications/read-all", { method: "POST" }).catch(() => undefined);
  }, [data]);

  return (
    <>
      <h1>Уведомления</h1>
      <ChannelsPanel />
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
