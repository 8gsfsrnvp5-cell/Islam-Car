"use client";

import { api, formatDate, formatRub } from "@islamic-car/shared";
import { useEffect, useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Field, Loading, Notice, PageHead } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Profile = { tax_regime: string; vat_payer: boolean; regimes: Record<string, string>; seller_regime: string };
type ParamDef = { title: string; unit: string; regimes: string[]; knowledge: string };
type ParamRow = { id: string; code: string; title: string; unit: string; value: string; effective_from: string; effective_to: string | null;
  source_url: string; status: string; knowledge_code: string; entered_by: string | null; approved_by: string | null };
type Step = { label: string; value_kopecks: number | null; text: string };
type TaxResult = { code: string; title: string; status: string; amount_kopecks: number | null; steps: Step[];
  params: { code: string; value: string; source_url: string; approved_by: string; knowledge_code: string }[]; warnings: string[]; basis: string[] };
type Calc = { period: { from: string; to: string }; regime_title: string; results: TaxResult[]; warnings: string[]; not_included: string[]; disclaimer: string };
type Ops = { receipts: { date: string; contract: string; amount_kopecks: number; document: string }[];
  expenses: { date: string; category: string; amount_kopecks: number; description: string }[];
  purchases: { date: string; car: string; amount_kopecks: number; purchased_from: string }[];
  sales: { number: string; signed_at: string; price: number; cost: number; markup: number }[];
  totals: Record<string, number> };
type Event = { id: string; title: string; due_date: string; knowledge_code: string; status: string; overdue: boolean; source_url: string };

function yearStart() { const d = new Date(); return `${d.getFullYear()}-01-01`; }
function todayIso() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }

function ProfileTab() {
  const canApprove = useCan("accounting.approve");
  const { data, error, setData } = useApi<Profile>("/api/admin/accounting/profile");
  const [form, setForm] = useState<{ tax_regime: string; vat_payer: boolean } | null>(null);
  const action = useAction();
  useEffect(() => { if (data && !form) setForm({ tax_regime: data.tax_regime, vat_payer: data.vat_payer }); }, [data, form]);
  if (!data || !form) return error ? <ErrorBox error={error} /> : <Loading />;
  const save = async () => { const r = await action.run(() => api<Profile>("/api/admin/accounting/profile", { method: "PUT", json: form })); if (r) setData(r); };
  return (
    <Card title="Налоговый профиль" subtitle="Устанавливает владелец по решению бухгалтера">
      <ErrorBox error={action.error} />
      <div className="form-grid">
        <Field label="Налоговый режим">
          <select value={form.tax_regime} onChange={(e) => setForm({ ...form, tax_regime: e.target.value })} disabled={!canApprove}>
            <option value="">— не выбран —</option>
            {Object.entries(data.regimes).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select>
        </Field>
        <label className="check" style={{ alignSelf: "end" }}><input type="checkbox" checked={form.vat_payer} onChange={(e) => setForm({ ...form, vat_payer: e.target.checked })} disabled={!canApprove} /><span className="small">Компания — плательщик НДС</span></label>
      </div>
      <p className="small muted" style={{ marginTop: 8 }}>Режим продавца в настройках: {data.seller_regime}. ОСНО в этой версии не рассчитывается.</p>
      {canApprove ? <button className="btn btn-primary btn-sm" onClick={save} disabled={action.busy}>Сохранить</button> : null}
    </Card>
  );
}

function ParamsTab() {
  const canWrite = useCan("accounting.write");
  const canApprove = useCan("accounting.approve");
  const { data, error, reload } = useApi<{ definitions: Record<string, ParamDef>; items: ParamRow[] }>("/api/admin/accounting/params");
  const [form, setForm] = useState({ code: "", value: "", effective_from: yearStart(), effective_to: "", source_url: "", note: "" });
  const action = useAction();
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (await action.run(() => api("/api/admin/accounting/params", { method: "POST", json: { ...form, effective_to: form.effective_to || null } }))) {
      setForm({ ...form, value: "", source_url: "", note: "" }); reload();
    }
  };
  const act = async (id: string, what: "approve" | "revoke") => { if (await action.run(() => api(`/api/admin/accounting/params/${id}/${what}`, { method: "POST" }))) reload(); };
  return (
    <>
      <Notice tone="warn" title="Ставки, лимиты и сроки не заполняются автоматически">
        Бухгалтер вносит значение из официального источника со ссылкой и периодом действия, владелец утверждает.
        В расчёте используются только утверждённые значения; если значение менялось внутри периода — расчёт не выполняется.
      </Notice>
      <ErrorBox error={action.error} />
      <Card title="Параметры правил" flush>
        {!data.items.length ? <Empty>Параметры не внесены — налоги не рассчитываются</Empty> : (
          <table>
            <thead><tr><th>Параметр</th><th>Значение</th><th>Период</th><th>Источник</th><th>Статус</th><th></th></tr></thead>
            <tbody>
              {data.items.map((p) => (
                <tr key={p.id}>
                  <td>{p.title}<div className="small muted mono">{p.knowledge_code}</div></td>
                  <td><strong>{p.value}</strong> {p.unit}</td>
                  <td className="small">{formatDate(p.effective_from)} — {p.effective_to ? formatDate(p.effective_to) : "…"}</td>
                  <td className="small"><a href={p.source_url} target="_blank" rel="noreferrer">ссылка</a><div className="muted">внёс: {p.entered_by}</div></td>
                  <td>{p.status === "approved" ? <><Badge tone="ok">утверждён</Badge><div className="small muted">{p.approved_by}</div></> : p.status === "draft" ? <Badge tone="warn">черновик</Badge> : <Badge>отозван</Badge>}</td>
                  <td className="right">
                    {canApprove && p.status === "draft" ? <button className="btn btn-sm" onClick={() => act(p.id, "approve")}>Утвердить</button> : null}
                    {canApprove && p.status === "approved" ? <button className="btn btn-sm btn-danger" onClick={() => act(p.id, "revoke")}>Отозвать</button> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {canWrite ? (
        <Card title="Внести значение">
          <form onSubmit={add} className="form-grid">
            <Field label="Параметр" wide>
              <select value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required>
                <option value="">— выберите —</option>
                {Object.entries(data.definitions).map(([k, d]) => <option key={k} value={k}>{d.title} ({d.unit})</option>)}
              </select>
            </Field>
            <Field label="Значение"><input value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} required /></Field>
            <Field label="Ссылка на официальный источник"><input value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} placeholder="https://…" required /></Field>
            <Field label="Действует с"><input type="date" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} required /></Field>
            <Field label="Действует по (необязательно)"><input type="date" value={form.effective_to} onChange={(e) => setForm({ ...form, effective_to: e.target.value })} /></Field>
            <Field label="Комментарий (регион, основание)" wide><input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
            <div className="wide"><button className="btn btn-primary" disabled={action.busy}>Сохранить черновик</button></div>
          </form>
        </Card>
      ) : null}
    </>
  );
}

function CalcTab() {
  const [period, setPeriod] = useState({ from: yearStart(), to: todayIso() });
  const { data, error, loading } = useApi<Calc>(`/api/admin/accounting/calculate?date_from=${period.from}&date_to=${period.to}`);
  return (
    <>
      <div className="actions" style={{ marginBottom: 12 }}>
        <input type="date" value={period.from} onChange={(e) => setPeriod({ ...period, from: e.target.value })} />
        <input type="date" value={period.to} onChange={(e) => setPeriod({ ...period, to: e.target.value })} />
      </div>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : data ? (
        <>
          <Notice tone="info">{data.disclaimer}</Notice>
          {data.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
          {data.results.map((r) => (
            <Card key={r.code} title={r.title} subtitle={r.status === "ok" ? `К уплате по расчёту: ${formatRub(r.amount_kopecks)}` : r.status === "not_applicable" ? "Не применяется" : "Не рассчитан"}>
              <table><tbody>{r.steps.map((s, i) => <tr key={i}><td className="small">{s.label}{s.text ? <span className="muted"> · {s.text}</span> : null}</td><td className="num">{s.value_kopecks === null ? "" : formatRub(s.value_kopecks)}</td></tr>)}</tbody></table>
              {r.params.length ? <p className="small" style={{ marginTop: 8 }}>Параметры: {r.params.map((p) => <span key={p.code}>{p.code} = {p.value} (утвердил {p.approved_by}, <a href={p.source_url} target="_blank" rel="noreferrer">источник</a>) </span>)}</p> : null}
              <p className="small muted">Основания: {r.basis.join(", ")}</p>
              {r.warnings.map((w) => <div key={w} className="small" style={{ color: "var(--warn)" }}>! {w}</div>)}
            </Card>
          ))}
          <p className="small muted">Не рассчитывается в этой версии: {data.not_included.join(", ")}.</p>
        </>
      ) : null}
    </>
  );
}

function OpsTab() {
  const [period, setPeriod] = useState({ from: yearStart(), to: todayIso() });
  const { data, error } = useApi<Ops>(`/api/admin/accounting/operations?date_from=${period.from}&date_to=${period.to}`);
  return (
    <>
      <div className="actions" style={{ marginBottom: 12 }}>
        <input type="date" value={period.from} onChange={(e) => setPeriod({ ...period, from: e.target.value })} />
        <input type="date" value={period.to} onChange={(e) => setPeriod({ ...period, to: e.target.value })} />
      </div>
      <ErrorBox error={error} />
      {!data ? <Loading /> : (
        <div className="grid grid-2">
          <Card title={`Поступления · ${formatRub(data.totals.receipts)}`} flush>
            <table><tbody>{data.receipts.map((r, i) => <tr key={i}><td className="small">{formatDate(r.date)}</td><td className="small">№ {r.contract}<div className="muted">{r.document}</div></td><td className="num">{formatRub(r.amount_kopecks)}</td></tr>)}</tbody></table>
          </Card>
          <Card title={`Расходы · ${formatRub(data.totals.expenses)}`} flush>
            <table><tbody>{data.expenses.map((e, i) => <tr key={i}><td className="small">{formatDate(e.date)}</td><td className="small">{e.category}<div className="muted">{e.description}</div></td><td className="num">{formatRub(e.amount_kopecks)}</td></tr>)}</tbody></table>
          </Card>
          <Card title={`Закупки автомобилей · ${formatRub(data.totals.purchases)}`} flush>
            <table><tbody>{data.purchases.map((p, i) => <tr key={i}><td className="small">{formatDate(p.date)}</td><td className="small">{p.car}<div className="muted">куплен у: {p.purchased_from}</div></td><td className="num">{formatRub(p.amount_kopecks)}</td></tr>)}</tbody></table>
          </Card>
          <Card title={`Продажи (подписанные договоры) · наценка ${formatRub(data.totals.sales_markup)}`} flush>
            <table><tbody>{data.sales.map((s) => <tr key={s.number}><td className="small">{formatDate(s.signed_at)}</td><td className="small">№ {s.number}<div className="muted">себестоимость {formatRub(s.cost)}</div></td><td className="num">{formatRub(s.price)}</td></tr>)}</tbody></table>
          </Card>
        </div>
      )}
    </>
  );
}

function CalendarTab() {
  const canWrite = useCan("accounting.write");
  const { data, reload } = useApi<Event[]>("/api/admin/accounting/calendar");
  const [form, setForm] = useState({ title: "", due_date: todayIso(), knowledge_code: "", source_url: "" });
  const action = useAction();
  const add = async (e: React.FormEvent) => { e.preventDefault(); if (await action.run(() => api("/api/admin/accounting/calendar", { method: "POST", json: form }))) { setForm({ ...form, title: "" }); reload(); } };
  const done = async (id: string) => { if (await action.run(() => api(`/api/admin/accounting/calendar/${id}/done`, { method: "POST" }))) reload(); };
  return (
    <div className="split">
      <Card title="Налоговый календарь" subtitle="Сроки вносит бухгалтер; за 7 дней создаётся задача" flush>
        {!data?.length ? <Empty>Сроки не внесены</Empty> : (
          <table><tbody>{data.map((e) => (
            <tr key={e.id}><td>{formatDate(e.due_date)}</td><td>{e.title}<div className="small muted">{e.knowledge_code}</div></td>
              <td>{e.status === "done" ? <Badge tone="ok">выполнено</Badge> : e.overdue ? <Badge tone="danger">просрочено</Badge> : <Badge tone="warn">ожидает</Badge>}</td>
              <td className="right">{canWrite && e.status === "open" ? <button className="btn btn-sm" onClick={() => done(e.id)}>Выполнено</button> : null}</td></tr>
          ))}</tbody></table>
        )}
      </Card>
      {canWrite ? (
        <Card title="Добавить срок">
          <ErrorBox error={action.error} />
          <form onSubmit={add} className="inline-form">
            <Field label="Что сдать или уплатить"><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required /></Field>
            <Field label="Срок"><input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} required /></Field>
            <Field label="Норма (код библиотеки)"><input value={form.knowledge_code} onChange={(e) => setForm({ ...form, knowledge_code: e.target.value })} placeholder="acc.nk.346_21" /></Field>
            <Field label="Источник"><input value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} /></Field>
            <button className="btn btn-primary" disabled={action.busy}>Добавить</button>
          </form>
        </Card>
      ) : null}
    </div>
  );
}

const TABS = { calc: "Расчёт налогов", ops: "Журнал операций", params: "Правила и ставки", calendar: "Налоговый календарь", profile: "Профиль" } as const;

export default function AccountingPage() {
  const can = useCan("accounting.read");
  const [tab, setTab] = useState<keyof typeof TABS>("calc");
  if (!can) return <><PageHead title="Бухгалтерия и налоги" /><Notice tone="warn">Недостаточно прав.</Notice></>;
  return (
    <>
      <PageHead title="Бухгалтерия и налоги" subtitle="Проверяемые расчёты по утверждённым правилам — с шагами, исходными операциями и основаниями" />
      <div className="tabs">{(Object.keys(TABS) as (keyof typeof TABS)[]).map((k) => <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{TABS[k]}</button>)}</div>
      {tab === "calc" ? <CalcTab /> : tab === "ops" ? <OpsTab /> : tab === "params" ? <ParamsTab /> : tab === "calendar" ? <CalendarTab /> : <ProfileTab />}
    </>
  );
}

