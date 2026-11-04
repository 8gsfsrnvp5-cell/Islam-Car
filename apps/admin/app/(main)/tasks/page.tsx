"use client";

import { TASK_STATUS, type StaffTask, api, formatDate, formatDateTime } from "@islamic-car/shared";
import Link from "next/link";
import { useState } from "react";

import { ReasonButton } from "@/components/Confirm";
import { Badge, Card, Empty, ErrorBox, Field, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

export default function TasksPage() {
  const [status, setStatus] = useState("open");
  const { data, error, loading, reload } = useApi<StaffTask[]>(`/api/admin/tasks${status ? `?status=${status}` : "?status="}`, 30000);
  const [form, setForm] = useState({ title: "", due_date: "", description: "" });
  const action = useAction();
  const todayIso = new Date().toISOString().slice(0, 10);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (await action.run(() => api("/api/admin/tasks", { method: "POST", json: { ...form, due_date: form.due_date || null } }))) {
      setForm({ title: "", due_date: "", description: "" }); reload();
    }
  }
  async function done(id: string, note: string) {
    if (await action.run(() => api(`/api/admin/tasks/${id}/done`, { method: "POST", json: { note } }))) reload();
  }

  return (
    <>
      <PageHead title="Задачи и сроки" subtitle="Задачи создаются вручную и фоновым контролем: просрочки, залоги, полисы, документы на утверждении" />
      <Notice tone="info">Система напоминает и готовит работу, но не применяет юридические меры сама. Решение принимает ответственный сотрудник.</Notice>
      <div className="tabs">
        {["open", "done", ""].map((s) => <button key={s || "all"} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>{s ? TASK_STATUS[s] : "Все"}</button>)}
      </div>
      <ErrorBox error={error ?? action.error} />
      <div className="split">
        <Card flush>
          {loading && !data ? <Loading /> : !data?.length ? <Empty>Задач нет</Empty> : (
            <table>
              <thead><tr><th>Задача</th><th>Срок</th><th>Статус</th><th></th></tr></thead>
              <tbody>
                {data.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <strong>{t.link ? <Link href={t.link}>{t.title}</Link> : t.title}</strong>
                      {t.description ? <div className="small muted">{t.description}</div> : null}
                      <div className="small muted">{t.automatic ? "создана автоматически" : "создана сотрудником"} · {formatDateTime(t.created_at)}</div>
                      {t.result_note ? <div className="small">Итог: {t.result_note}</div> : null}
                    </td>
                    <td className="small">{t.due_date ? <>{formatDate(t.due_date)}{t.status === "open" && t.due_date < todayIso ? <div><Badge tone="danger">просрочена</Badge></div> : null}</> : "—"}</td>
                    <td><StatusBadge status={t.status} labels={TASK_STATUS} /></td>
                    <td className="right">{t.status === "open" ? <ReasonButton label="Выполнено" placeholder="Что сделано" submitLabel="Закрыть" minLength={0} onSubmit={(note) => done(t.id, note)} small /> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Новая задача">
          <form onSubmit={add} className="inline-form">
            <Field label="Задача"><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required minLength={3} /></Field>
            <Field label="Срок"><input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} /></Field>
            <Field label="Описание"><textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
            <button className="btn btn-primary" disabled={action.busy}>Добавить</button>
          </form>
        </Card>
      </div>
    </>
  );
}
