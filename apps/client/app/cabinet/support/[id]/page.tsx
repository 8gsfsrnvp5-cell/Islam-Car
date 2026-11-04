"use client";

import { THREAD_STATUS, THREAD_TOPIC, type Thread, api, errorText, formatDateTime } from "@islamic-car/shared";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useClientApi } from "@/lib/useClientApi";

export default function ThreadPage() {
  const { id } = useParams<{ id: string }>();
  const { data: t, error, setData } = useClientApi<Thread>(`/api/client/threads/${id}`, 15000);
  const [body, setBody] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);

  if (error && !t) return <div className="notice danger">{error}</div>;
  if (!t) return <p>Загрузка…</p>;

  async function send(e: React.FormEvent) {
    e.preventDefault();
    try {
      setData(await api<Thread>(`/api/client/threads/${id}/messages`, { method: "POST", json: { body } }));
      setBody("");
      setSendError(null);
    } catch (err) {
      setSendError(errorText(err));
    }
  }

  return (
    <>
      <p><Link href="/cabinet/support">← Обращения</Link></p>
      <h1>{t.subject}</h1>
      <p className="muted">{THREAD_TOPIC[t.topic]} · <span className="badge">{THREAD_STATUS[t.status]}</span></p>
      <div className="panel">
        <div className="chat">
          {t.messages?.map((m) => (
            <div key={m.id} className={`msg ${m.from_staff ? "" : "mine"}`}>
              <small>{m.from_staff ? `Islamic Car · ${m.author}` : "Вы"} · {formatDateTime(m.created_at)}</small>
              {m.body}
            </div>
          ))}
        </div>
        {t.status !== "closed" ? (
          <form className="form" onSubmit={send}>
            <textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Ваше сообщение" required />
            {sendError ? <div className="form-error">{sendError}</div> : null}
            <div><button className="btn btn-primary">Отправить</button></div>
          </form>
        ) : <p className="muted">Обращение закрыто. Если вопрос остался — создайте новое.</p>}
      </div>
    </>
  );
}
