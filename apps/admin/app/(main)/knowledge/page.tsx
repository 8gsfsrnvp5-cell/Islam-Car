"use client";

import { api, formatDate, formatDateTime } from "@islamic-car/shared";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Field, Loading, Notice, PageHead } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Item = {
  library: string; code: string; version: string; title: string; act: string; article: string; summary: string;
  source_url: string; source_hint: string; topics: string[]; effective_from: string | null; effective_to: string | null;
  last_checked: string | null; problems: string[]; reliable: boolean;
  review: { status: string; reviewer_name: string; reviewer_role: string; note: string; reviewed_at: string } | null;
};
type Listing = { items: Item[]; summary: Record<string, { title: string; total: number; reliable: number }> };

const ROLES: Record<string, string> = { legal: "юрист", accounting: "бухгалтер", "islamic-finance": "специалист по шариату" };

function ReviewForm({ item, onDone }: { item: Item; onDone: () => void }) {
  const [form, setForm] = useState({ reviewer_name: "", reviewer_role: ROLES[item.library], note: "" });
  const action = useAction();
  const send = async (status: "approved" | "rejected") => {
    if (await action.run(() => api(`/api/admin/knowledge/${item.code}/review`, { method: "POST", json: { ...form, status, version: item.version } }))) onDone();
  };
  return (
    <div className="inline-form" style={{ marginTop: 10 }}>
      <ErrorBox error={action.error} />
      <Notice tone="info">Фиксируется заключение внешнего специалиста по точному тексту записи. Изменение записи в репозитории снимет заключение.</Notice>
      <div className="form-grid">
        <Field label="ФИО специалиста"><input value={form.reviewer_name} onChange={(e) => setForm({ ...form, reviewer_name: e.target.value })} /></Field>
        <Field label="Роль"><input value={form.reviewer_role} onChange={(e) => setForm({ ...form, reviewer_role: e.target.value })} /></Field>
        <Field label="Заключение / комментарий" wide><input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
      </div>
      <div className="actions">
        <button className="btn btn-primary btn-sm" disabled={form.reviewer_name.trim().length < 3 || action.busy} onClick={() => send("approved")}>Подтверждено специалистом</button>
        <button className="btn btn-danger btn-sm" disabled={form.reviewer_name.trim().length < 3 || action.busy} onClick={() => send("rejected")}>Отклонено</button>
      </div>
    </div>
  );
}

export default function KnowledgePage() {
  const canReview = useCan("knowledge.review");
  const [library, setLibrary] = useState("legal");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<Listing>(`/api/admin/knowledge?library=${library}${q ? `&q=${encodeURIComponent(q)}` : ""}`);

  return (
    <>
      <PageHead title="Библиотеки знаний" subtitle="Нормы и принципы, на которые опираются документы, расчёты и агенты" />
      <Notice tone="warn" title="Как пользоваться">
        Записи — указатели на нормы с кратким изложением, а не тексты законов. Пока специалист не внёс даты действия, точную ссылку
        на официальную публикацию и не дал заключение, система считает норму непроверенной и пишет «Требуется проверка».
        Правки записей вносятся в репозиторий (<code>knowledge/*/records.json</code>), заключения — здесь.
      </Notice>
      <div className="actions" style={{ marginBottom: 12 }}>
        <div className="tabs" style={{ margin: 0 }}>
          {Object.entries(data?.summary ?? { legal: { title: "Юридическая" }, accounting: { title: "Бухгалтерская и налоговая" }, "islamic-finance": { title: "Исламское финансирование" } })
            .map(([k, v]) => (
              <button key={k} className={library === k ? "active" : ""} onClick={() => { setLibrary(k); setOpen(null); }}>
                {v.title}{"total" in v ? ` · ${(v as { reliable: number }).reliable}/${(v as { total: number }).total}` : ""}
              </button>
            ))}
        </div>
        <input type="search" placeholder="Поиск по названию, акту, статье" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 300 }} />
      </div>
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.items.length ? <Empty>Записей нет</Empty> : (
          <table>
            <thead><tr><th>Норма</th><th>Акт и статья</th><th>Действует</th><th>Статус</th></tr></thead>
            <tbody>
              {data.items.map((i) => (
                <tr key={`${i.code}-${i.version}`}>
                  <td style={{ maxWidth: 380 }}>
                    <button className="link-btn" onClick={() => setOpen(open === i.code ? null : i.code)}><strong>{i.title}</strong></button>
                    <div className="small muted mono">{i.code} · ред. {i.version}</div>
                    {open === i.code ? (
                      <div style={{ marginTop: 8 }}>
                        <p className="small">{i.summary}</p>
                        <p className="small">Источник: {i.source_url ? <a href={i.source_url} target="_blank" rel="noreferrer">{i.source_url}</a> : "—"} · {i.source_hint}</p>
                        {i.review ? <p className="small">Заключение: {i.review.status === "approved" ? "подтверждено" : "отклонено"} — {i.review.reviewer_name} ({i.review.reviewer_role}), {formatDateTime(i.review.reviewed_at)}{i.review.note ? `. ${i.review.note}` : ""}</p> : null}
                        {canReview ? <ReviewForm item={i} onDone={() => { setOpen(null); reload(); }} /> : null}
                      </div>
                    ) : null}
                  </td>
                  <td className="small">{i.act}<div className="muted">{i.article}</div></td>
                  <td className="small">{i.effective_from ? `с ${formatDate(i.effective_from)}` : "дата не внесена"}{i.effective_to ? ` по ${formatDate(i.effective_to)}` : ""}
                    <div className="muted">сверено: {i.last_checked ? formatDate(i.last_checked) : "нет"}</div></td>
                  <td>{i.reliable ? <Badge tone="ok">Проверено</Badge> : <Badge tone="warn">Требуется проверка</Badge>}
                    {!i.reliable ? <ul className="small muted" style={{ margin: "4px 0 0", paddingLeft: 16 }}>{i.problems.map((p) => <li key={p}>{p}</li>)}</ul> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
