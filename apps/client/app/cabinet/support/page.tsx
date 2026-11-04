"use client";

import { THREAD_STATUS, THREAD_TOPIC, type ClientContract, type Thread, api, errorText, formatDateTime } from "@islamic-car/shared";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { useClientApi } from "@/lib/useClientApi";

const SUBJECTS: Record<string, string> = {
  early_repayment: "Досрочное погашение",
  schedule_change: "Изменение графика платежей",
  payment_difficulty: "Сложности с очередным платежом",
};

function SupportView() {
  const router = useRouter();
  const params = useSearchParams();
  const threads = useClientApi<Thread[]>("/api/client/threads", 20000);
  const contracts = useClientApi<ClientContract[]>("/api/client/contracts");
  const initialTopic = params.get("topic") ?? "general";
  const [form, setForm] = useState({
    topic: initialTopic, contract_id: params.get("contract") ?? "", subject: SUBJECTS[initialTopic] ?? "", body: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const t = await api<Thread>("/api/client/threads", { method: "POST", json: { ...form, contract_id: form.contract_id || null } });
      router.push(`/cabinet/support/${t.id}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Обращения</h1>
      <div className="panel">
        <h2>Новое обращение</h2>
        {["schedule_change", "payment_difficulty", "early_repayment"].includes(form.topic) ? (
          <div className="notice info">Запрос рассматривает менеджер. Договор и график не меняются автоматически — изменения оформляются дополнительным соглашением.</div>
        ) : null}
        <form className="form" onSubmit={create}>
          <div className="form-row">
            <label className="field"><span>Тема</span>
              <select value={form.topic} onChange={(e) => setForm({ ...form, topic: e.target.value, subject: form.subject || SUBJECTS[e.target.value] || "" })}>
                {Object.entries(THREAD_TOPIC).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
              </select>
            </label>
            <label className="field"><span>Договор</span>
              <select value={form.contract_id} onChange={(e) => setForm({ ...form, contract_id: e.target.value })}>
                <option value="">— не относится к договору —</option>
                {contracts.data?.map((c) => <option key={c.id} value={c.id}>№ {c.number} · {c.car.title}</option>)}
              </select>
            </label>
          </div>
          <label className="field"><span>Заголовок</span><input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} required minLength={3} /></label>
          <label className="field"><span>Сообщение</span><textarea value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} required /></label>
          {error ? <div className="form-error">{error}</div> : null}
          <div><button className="btn btn-primary" disabled={busy}>Отправить</button></div>
        </form>
      </div>
      <div className="panel">
        <h2>Мои обращения</h2>
        {!threads.data ? <p>Загрузка…</p> : !threads.data.length ? <p className="muted">Обращений пока нет.</p> : threads.data.map((t) => (
          <div className="list-item" key={t.id}>
            <div><Link href={`/cabinet/support/${t.id}`}>{t.subject}</Link><div className="small muted">{THREAD_TOPIC[t.topic]} · {formatDateTime(t.updated_at)}</div></div>
            <span className={`badge ${t.status === "answered" ? "ok" : t.status === "open" ? "warn" : ""}`}>{THREAD_STATUS[t.status]}</span>
          </div>
        ))}
      </div>
    </>
  );
}

export default function SupportPage() {
  return <Suspense fallback={<p>Загрузка…</p>}><SupportView /></Suspense>;
}
