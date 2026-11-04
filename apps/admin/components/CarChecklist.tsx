"use client";

import { api, formatDateTime } from "@islamic-car/shared";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, ErrorBox, Field, Notice } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Item = { code: string; title: string; required: boolean; sources: string[]; status: string; source: string; reference: string;
  notes: string; checked_at: string | null; has_evidence: boolean; check_id: string | null };
type Summary = { items: Item[]; verdict: string; state: string; statuses: Record<string, string> };

const TONE: Record<string, "ok" | "danger" | "warn" | undefined> = { ok: "ok", problem: "danger", not_checked: "warn", not_applicable: undefined };

export function CarChecklist({ carId }: { carId: string }) {
  const canWrite = useCan("cars.write");
  const { data, error, setData } = useApi<Summary>(`/api/admin/cars/${carId}/checks`);
  const [open, setOpen] = useState<string | null>(null);
  const [form, setForm] = useState({ status: "ok", source: "", reference: "", notes: "" });
  const [file, setFile] = useState<File | null>(null);
  const action = useAction();
  if (!data) return error ? <ErrorBox error={error} /> : null;

  const start = (it: Item) => { setOpen(it.code); setForm({ status: "ok", source: it.sources[0], reference: "", notes: "" }); setFile(null); };
  const save = async (code: string) => {
    const body = new FormData();
    body.append("item_code", code);
    Object.entries(form).forEach(([k, v]) => body.append(k, v));
    if (file) body.append("file", file);
    const r = await action.run(() => api<Summary>(`/api/admin/cars/${carId}/checks`, { method: "POST", body }));
    if (r) { setData(r); setOpen(null); }
  };

  return (
    <Card title="Проверка перед покупкой" subtitle="Результаты — только из законных источников с указанием источника; система их не придумывает">
      <Notice tone={data.state === "ok" ? "ok" : data.state === "problem" ? "danger" : "warn"}>{data.verdict}</Notice>
      <ErrorBox error={action.error} />
      {data.items.map((it) => (
        <div key={it.code} style={{ borderBottom: "1px dashed var(--line)", padding: "8px 0" }}>
          <div className="actions" style={{ justifyContent: "space-between" }}>
            <span className="small"><strong>{it.title}</strong>{it.required ? "" : <span className="muted"> · по желанию</span>}</span>
            <span className="actions">
              <Badge tone={TONE[it.status]}>{data.statuses[it.status]}</Badge>
              {canWrite && open !== it.code ? <button className="link-btn small" onClick={() => start(it)}>внести</button> : null}
            </span>
          </div>
          {it.checked_at ? <div className="small muted">{it.source}{it.reference ? ` · ${it.reference}` : ""} · {formatDateTime(it.checked_at)}
            {it.has_evidence ? <> · <a href={`/api/admin/cars/${carId}/checks/${it.check_id}/evidence`} target="_blank" rel="noreferrer">подтверждение</a></> : null}
            {it.notes ? <div>{it.notes}</div> : null}</div> : null}
          {open === it.code ? (
            <div className="inline-form" style={{ marginTop: 8 }}>
              <Field label="Результат">
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {Object.entries(data.statuses).filter(([k]) => k !== "not_checked").map(([k, t]) => <option key={k} value={k}>{t}</option>)}
                </select>
              </Field>
              <Field label="Источник">
                <input list={`src-${it.code}`} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} />
                <datalist id={`src-${it.code}`}>{it.sources.map((s) => <option key={s} value={s} />)}</datalist>
              </Field>
              <Field label="Номер запроса, дата, документ"><input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /></Field>
              <Field label="Комментарий"><input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
              <Field label="Подтверждение (скриншот или выписка: PDF, JPEG, PNG)"><input type="file" accept="application/pdf,image/jpeg,image/png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
              <div className="actions"><button className="btn btn-primary btn-sm" onClick={() => save(it.code)} disabled={action.busy}>Сохранить</button><button className="btn btn-sm" onClick={() => setOpen(null)}>Отмена</button></div>
            </div>
          ) : null}
        </div>
      ))}
      <p className="small muted" style={{ marginTop: 8 }}>Автоматические запросы к источникам (ГИБДД, реестр залогов) появятся после официального подключения источников по договорам.</p>
    </Card>
  );
}
