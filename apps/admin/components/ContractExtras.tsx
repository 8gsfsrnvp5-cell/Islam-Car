"use client";

import {
  DOC_STATUS, INSURANCE_KIND, PLEDGE_STATUS, type DocItem, type DocTemplate, type InsurancePolicy, type Pledge, type StaffContract,
  api, formatDate, formatRub,
} from "@islamic-car/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DocChecks } from "@/components/DocumentView";
import { useCan } from "@/components/Shell";
import { Badge, Card, ErrorBox, Field, Notice, StatusBadge } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

function todayIso(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

type Missing = { message: string; missing: string[] };

function DocumentsCard({ contract }: { contract: StaffContract }) {
  const router = useRouter();
  const canWrite = useCan("documents.content");
  const docs = useApi<DocItem[]>(`/api/admin/documents?contract_id=${contract.id}`);
  const templates = useApi<DocTemplate[]>("/api/admin/templates");
  const [code, setCode] = useState("");
  const [params, setParams] = useState<Record<string, string | boolean>>({});
  const [missing, setMissing] = useState<Missing | null>(null);
  const action = useAction();

  const available = (templates.data ?? []).filter((t) => t.scope === "contract" && t.code !== "schedule_addendum");
  const tpl = available.find((t) => t.code === code);

  async function create() {
    setMissing(null);
    try {
      const doc = await api<DocItem>("/api/admin/documents", { method: "POST", json: { template_code: code, contract_id: contract.id, params } });
      router.push(`/documents/${doc.id}`);
    } catch (e) {
      const detail = (e as { detail?: unknown }).detail as Missing | undefined;
      if (detail && typeof detail === "object" && "missing" in detail) setMissing(detail);
      else action.setError(e instanceof Error ? e.message : "Ошибка");
    }
  }

  return (
    <Card title="Документы" subtitle="Формируются из шаблонов и данных карточек; недостающие данные система запрашивает">
      <ErrorBox error={docs.error ?? action.error} />
      {docs.data?.length ? (
        <table style={{ marginBottom: 12 }}>
          <tbody>
            {docs.data.map((d) => (
              <tr key={d.id}>
                <td>{canWrite ? <Link href={`/documents/${d.id}`}>{d.title}</Link> : d.title}{d.watermark ? <div className="small muted">{d.watermark}</div> : null}</td>
                <td style={{ width: 150 }}><StatusBadge status={d.status} labels={DOC_STATUS} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="small muted">Документов по договору ещё нет.</p>}
      {canWrite ? (
        <div className="inline-form">
          <Field label="Сформировать документ">
            <select value={code} onChange={(e) => { setCode(e.target.value); setParams({}); setMissing(null); }}>
              <option value="">— выберите шаблон —</option>
              {available.map((t) => <option key={t.code} value={t.code}>{t.title}{t.approved ? "" : " (черновик шаблона)"}</option>)}
            </select>
          </Field>
          {tpl?.params.map((p) => p.type === "bool" ? (
            <label key={p.name} className="check"><input type="checkbox" checked={Boolean(params[p.name])} onChange={(e) => setParams({ ...params, [p.name]: e.target.checked })} /><span className="small">{p.label}</span></label>
          ) : (
            <Field key={p.name} label={`${p.label}${p.required ? " *" : ""}`}>
              <input value={String(params[p.name] ?? "")} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} />
            </Field>
          ))}
          {missing ? (
            <Notice tone="danger" title="Не хватает данных — документ не сформирован">
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{missing.missing.map((m) => <li key={m} className="small">{m}</li>)}</ul>
            </Notice>
          ) : null}
          {code ? <div><button className="btn btn-primary" onClick={create}>Сформировать проект</button></div> : null}
        </div>
      ) : null}
    </Card>
  );
}

function PledgeCard({ contract }: { contract: StaffContract }) {
  const canWrite = useCan("contracts.write");
  const { data, error, loading, setData } = useApi<Pledge | null>(`/api/admin/contracts/${contract.id}/pledge`);
  const [next, setNext] = useState("");
  const [form, setForm] = useState({ registry_number: "", registered_on: "", notary: "", release_number: "", released_on: "", notes: "" });
  const action = useAction();
  if (error) return <ErrorBox error={error} />;
  if (loading) return null;
  if (!data) {
    // Договоры, подписанные до версии 2, не имеют карточки залога
    const createCard = async () => {
      const r = await action.run(() => api<Pledge>(`/api/admin/contracts/${contract.id}/pledge`, { method: "PUT", json: { status: "planned" } }));
      if (r) setData(r);
    };
    return (
      <Card title="Залог">
        <ErrorBox error={action.error} />
        <p className="small muted">Карточка контроля залога для этого договора ещё не создана.</p>
        {canWrite ? <button className="btn btn-sm" onClick={createCard} disabled={action.busy}>Создать карточку залога</button> : null}
      </Card>
    );
  }

  async function save() {
    const r = await action.run(() => api<Pledge>(`/api/admin/contracts/${contract.id}/pledge`, {
      method: "PUT",
      json: { status: next || data!.status, registry_number: form.registry_number || data!.registry_number, notary: form.notary || data!.notary,
        registered_on: form.registered_on || data!.registered_on, release_number: form.release_number || data!.release_number,
        released_on: form.released_on || data!.released_on, notes: form.notes || data!.notes },
    }));
    if (r) { setData(r); setNext(""); }
  }

  return (
    <Card title="Залог" subtitle="Внутренний контроль. Статус «зарегистрирован» — только с номером уведомления из реестра">
      <ErrorBox error={action.error} />
      <dl className="kv">
        <dt>Статус</dt><dd><StatusBadge status={data.status} labels={PLEDGE_STATUS} /></dd>
        <dt>Уведомление о залоге</dt><dd>{data.registry_number ? `${data.registry_number} от ${formatDate(data.registered_on)}` : "—"}</dd>
        <dt>Нотариус</dt><dd>{data.notary || "—"}</dd>
        {data.release_number ? <><dt>Исключение сведений</dt><dd>{data.release_number} от {formatDate(data.released_on)}</dd></> : null}
      </dl>
      {canWrite && data.allowed_next.length ? (
        <div className="inline-form" style={{ marginTop: 12 }}>
          <Field label="Следующий шаг">
            <select value={next} onChange={(e) => setNext(e.target.value)}>
              <option value="">— выберите —</option>
              {data.allowed_next.map((s) => <option key={s} value={s}>{PLEDGE_STATUS[s]}</option>)}
            </select>
          </Field>
          {next === "submitted" ? <Field label="Нотариус"><input value={form.notary} onChange={(e) => setForm({ ...form, notary: e.target.value })} /></Field> : null}
          {next === "registered" ? (
            <>
              <Field label="Номер уведомления о залоге"><input value={form.registry_number} onChange={(e) => setForm({ ...form, registry_number: e.target.value })} /></Field>
              <Field label="Дата регистрации"><input type="date" value={form.registered_on} onChange={(e) => setForm({ ...form, registered_on: e.target.value })} /></Field>
            </>
          ) : null}
          {next === "released" ? (
            <>
              <Field label="Номер уведомления об исключении"><input value={form.release_number} onChange={(e) => setForm({ ...form, release_number: e.target.value })} /></Field>
              <Field label="Дата"><input type="date" value={form.released_on} onChange={(e) => setForm({ ...form, released_on: e.target.value })} /></Field>
            </>
          ) : null}
          {next ? <div><button className="btn btn-primary btn-sm" onClick={save} disabled={action.busy}>Сохранить</button></div> : null}
        </div>
      ) : null}
    </Card>
  );
}

function InsuranceCard({ contract }: { contract: StaffContract }) {
  const canWrite = useCan("contracts.write");
  const { data, reload } = useApi<InsurancePolicy[]>(`/api/admin/insurance?contract_id=${contract.id}`);
  const [form, setForm] = useState({ kind: "osago", number: "", insurer: "", valid_from: todayIso(), valid_to: todayIso(365), required_by_contract: true });
  const [open, setOpen] = useState(false);
  const action = useAction();

  async function add() {
    if (await action.run(() => api("/api/admin/insurance", { method: "POST", json: { ...form, car_id: contract.car.id, contract_id: contract.id } }))) {
      setOpen(false); reload();
    }
  }

  return (
    <Card title="Страхование" subtitle="За 30 дней до окончания обязательного полиса создаётся задача">
      <ErrorBox error={action.error} />
      {data?.length ? data.map((p) => (
        <div key={p.id} className="small" style={{ marginBottom: 6 }}>
          <strong>{INSURANCE_KIND[p.kind]}</strong> № {p.number} · {p.insurer || "—"} · до {formatDate(p.valid_to)} {p.required_by_contract ? <Badge tone="info">по договору</Badge> : null}
        </div>
      )) : <p className="small muted">Полисы не внесены.</p>}
      {canWrite && !open ? <button className="btn btn-sm" onClick={() => setOpen(true)}>Добавить полис</button> : null}
      {open ? (
        <div className="inline-form" style={{ marginTop: 10 }}>
          <Field label="Вид"><select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>{Object.entries(INSURANCE_KIND).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></Field>
          <Field label="Номер полиса"><input value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} /></Field>
          <Field label="Страховщик"><input value={form.insurer} onChange={(e) => setForm({ ...form, insurer: e.target.value })} /></Field>
          <Field label="Действует с"><input type="date" value={form.valid_from} onChange={(e) => setForm({ ...form, valid_from: e.target.value })} /></Field>
          <Field label="Действует до"><input type="date" value={form.valid_to} onChange={(e) => setForm({ ...form, valid_to: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={form.required_by_contract} onChange={(e) => setForm({ ...form, required_by_contract: e.target.checked })} /><span className="small">Обязателен по договору</span></label>
          <div className="actions"><button className="btn btn-primary btn-sm" onClick={add} disabled={action.busy}>Сохранить</button><button className="btn btn-sm" onClick={() => setOpen(false)}>Отмена</button></div>
        </div>
      ) : null}
    </Card>
  );
}

type Preview = { new_schedule: { seq: number; due_date: string; amount_kopecks: number }[]; paid_kopecks: number; monthly_kopecks: number; checks: { ok: boolean; message: string }[] };
type AddendaList = { addenda: { id: string; number: number; status: string; signed_on: string | null; term_months: number; document_id: string | null }[]; history: unknown[] };

function AddendumCard({ contract }: { contract: StaffContract }) {
  const router = useRouter();
  const canWrite = useCan("contracts.write");
  const list = useApi<AddendaList>(`/api/admin/contracts/${contract.id}/addenda`);
  const [form, setForm] = useState({ term_months: "12", first_payment_date: todayIso(30), reason: "" });
  const [preview, setPreview] = useState<Preview | null>(null);
  const action = useAction();
  const body = () => ({ term_months: Number(form.term_months), first_payment_date: form.first_payment_date, reason: form.reason });

  async function calc() {
    const r = await action.run(() => api<Preview>(`/api/admin/contracts/${contract.id}/addenda/preview`, { method: "POST", json: body() }));
    if (r) setPreview(r);
  }
  async function create() {
    const r = await action.run(() => api<{ document_id: string }>(`/api/admin/contracts/${contract.id}/addenda`, { method: "POST", json: body() }));
    if (r) router.push(`/documents/${r.document_id}`);
  }

  return (
    <Card title="Изменение графика" subtitle="Дополнительным соглашением. Цена договора не меняется, надбавок за отсрочку нет">
      <ErrorBox error={action.error ?? list.error} />
      {list.data?.addenda.length ? list.data.addenda.map((a) => (
        <div key={a.id} className="small" style={{ marginBottom: 6 }}>
          Соглашение № {a.number}: {a.term_months} мес. · <StatusBadge status={a.status === "draft" ? "pending_approval" : a.status === "signed" ? "signed" : "cancelled"} labels={{ pending_approval: "Готовится", signed: `Подписано ${formatDate(a.signed_on)}`, cancelled: "Отменено" }} />
          {a.document_id ? <> · <Link href={`/documents/${a.document_id}`}>документ</Link></> : null}
        </div>
      )) : null}
      {canWrite && contract.status === "signed" ? (
        <div className="inline-form">
          <div className="form-grid">
            <Field label="Новый срок для остатка, мес."><input type="number" min={1} max={120} value={form.term_months} onChange={(e) => { setForm({ ...form, term_months: e.target.value }); setPreview(null); }} /></Field>
            <Field label="Первый платёж по новому графику"><input type="date" value={form.first_payment_date} onChange={(e) => { setForm({ ...form, first_payment_date: e.target.value }); setPreview(null); }} /></Field>
            <Field label="Основание" wide><input value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="Например: просьба покупателя от 02.11.2026" /></Field>
          </div>
          <div className="actions">
            <button className="btn btn-sm" onClick={calc} disabled={action.busy}>Рассчитать</button>
            {preview ? <button className="btn btn-primary btn-sm" onClick={create} disabled={action.busy}>Подготовить соглашение</button> : null}
          </div>
          {preview ? (
            <>
              <p className="small">Уже оплачено {formatRub(preview.paid_kopecks)} · новый ежемесячный платёж ≈ <strong>{formatRub(preview.monthly_kopecks)}</strong></p>
              <DocChecks checks={preview.checks.map((c) => ({ code: "", level: c.ok ? "ok" : "error", message: c.message }))} />
            </>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

type Murabaha = { items: { code: string; title: string; state: string; message: string; source: string; rule_confirmed: boolean }[];
  verdict: string; final_note: string; failed: number };

function MurabahaCard({ contract }: { contract: StaffContract }) {
  const { data, error } = useApi<Murabaha>(`/api/admin/contracts/${contract.id}/murabaha`);
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const mark: Record<string, string> = { ok: "✓", problem: "✕", info: "i" };
  const tone: Record<string, string> = { ok: "ok", problem: "bad", info: "warn" };
  return (
    <Card title="Принципы мурабахи" subtitle={data.verdict}>
      <ul className="checks">
        {data.items.map((i) => (
          <li key={i.code}>
            <span className={`mark ${tone[i.state]}`}>{mark[i.state]}</span>
            <span className="small"><strong>{i.title}.</strong> {i.message}
              <span className="muted"> · {i.rule_confirmed ? "правило подтверждено специалистом" : "правило не подтверждено специалистом"}</span></span>
          </li>
        ))}
      </ul>
      <p className="small muted" style={{ marginTop: 8 }}>{data.final_note}</p>
    </Card>
  );
}

export function ContractExtras({ contract }: { contract: StaffContract }) {
  const live = contract.status === "signed" || contract.status === "completed";
  return (
    <>
      <DocumentsCard contract={contract} />
      {live ? <MurabahaCard contract={contract} /> : null}
      {live ? <AddendumCard contract={contract} /> : null}
      {live ? <PledgeCard contract={contract} /> : null}
      {live ? <InsuranceCard contract={contract} /> : null}
    </>
  );
}
