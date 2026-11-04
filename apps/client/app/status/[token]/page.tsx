"use client";

import { APPLICATION_STATUS, type PublicApplication, api, errorText, formatDateTime } from "@islamic-car/shared";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

const TONE: Record<string, string> = { converted: "ok", rejected: "danger", withdrawn: "", new: "warn" };
const FINAL = ["converted", "rejected", "withdrawn"];

function StatusView() {
  const { token } = useParams<{ token: string }>();
  const isNew = useSearchParams().get("new") === "1";
  const [app, setApp] = useState<PublicApplication | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  const load = useCallback(async () => {
    try { setApp(await api<PublicApplication>(`/api/public/applications/${token}`)); setError(null); }
    catch (e) { setError(errorText(e)); }
  }, [token]);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  async function withdraw() {
    setAsking(false);
    try { setApp(await api<PublicApplication>(`/api/public/applications/${token}/withdraw`, { method: "POST" })); }
    catch (e) { setError(errorText(e)); }
  }

  if (error && !app) return <div className="notice danger">{error}</div>;
  if (!app) return <p>Загрузка…</p>;

  return (
    <>
      {isNew ? (
        <div className="notice ok">
          <strong>Заявка отправлена</strong>
          Сохраните адрес этой страницы — по нему можно проверить статус заявки. Никому не передавайте ссылку.
        </div>
      ) : null}
      <div className="panel">
        <div className="muted small">{app.kind === "custom_order" ? "Запрос на подбор" : "Заявка на автомобиль"}</div>
        <h2>{app.car_title ?? app.wanted ?? "Заявка"}</h2>
        <p><span className={`badge ${TONE[app.status] ?? "ok"}`}>{APPLICATION_STATUS[app.status] ?? app.status}</span></p>
        {app.public_message ? <p>{app.public_message}</p> : null}
        <p className="small muted">Подана {formatDateTime(app.created_at)} · обновлена {formatDateTime(app.updated_at)}</p>
        {!FINAL.includes(app.status) ? (asking ? (
          <div className="actions">
            <span className="small">Отозвать заявку? Это действие нельзя отменить.</span>
            <button className="btn btn-sm" onClick={withdraw}>Да, отозвать</button>
            <button className="btn btn-sm" onClick={() => setAsking(false)}>Нет</button>
          </div>
        ) : <button className="btn btn-sm" onClick={() => setAsking(true)}>Отозвать заявку</button>) : null}
      </div>
      <div className="panel">
        <h2>История</h2>
        <ul className="timeline">
          {app.history.map((h, i) => (
            <li key={i}><strong>{APPLICATION_STATUS[h.status] ?? h.status}</strong>{h.message ? ` — ${h.message}` : ""}<small>{formatDateTime(h.at)}</small></li>
          ))}
        </ul>
      </div>
      {app.status === "converted" ? (
        <div className="notice info">Договор заключён. Войти в <Link href="/cabinet">личный кабинет</Link> можно после получения ссылки от менеджера.</div>
      ) : null}
    </>
  );
}

export default function StatusPage() {
  return (
    <div className="container" style={{ maxWidth: 720 }}>
      <h1 style={{ marginTop: 32 }}>Статус заявки</h1>
      <Suspense fallback={<p>Загрузка…</p>}><StatusView /></Suspense>
    </div>
  );
}
