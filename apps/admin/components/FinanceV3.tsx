"use client";

import { api, formatDate, formatMonth, formatRub, rublesToKopecks } from "@islamic-car/shared";
import { useEffect, useState } from "react";

import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Field, Loading, Notice, Stat } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Position = {
  cash: { as_of: string; amount_kopecks: number } | null; free_cash_kopecks: number | null; monthly_opex_kopecks: number;
  reserve: { items: { code: string; title: string; amount_kopecks: number; basis: string }[]; total_kopecks: number };
  policy: { opex_months: number; aging: Record<string, number>; approved_at?: string; approved_by?: string };
  forecast: { month: string; expected_kopecks: number }[]; contracts: { number: string; client: string; outstanding_kopecks: number }[];
  warnings: string[]; note: string;
};

function todayIso() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }

export function PositionCard({ onLoaded }: { onLoaded?: (p: Position) => void }) {
  const canCash = useCan("expenses.write");
  const canPolicy = useCan("settings.write");
  const { data, error, setData } = useApi<Position>("/api/admin/finance/position");
  const [cash, setCash] = useState("");
  const [policy, setPolicy] = useState<{ opex_months: string; a: string; b: string; c: string } | null>(null);
  const action = useAction();
  useEffect(() => { if (data) onLoaded?.(data); }, [data, onLoaded]);
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;

  const saveCash = async () => {
    const k = rublesToKopecks(cash);
    if (k === null || Number.isNaN(k)) { action.setError("Укажите сумму в рублях"); return; }
    const r = await action.run(() => api<Position>("/api/admin/finance/cash", { method: "POST", json: { as_of: todayIso(), amount_kopecks: k, note: "по выписке и кассе" } }));
    if (r) { setData(r); setCash(""); }
  };
  const savePolicy = async () => {
    const p = policy!;
    const r = await action.run(() => api<Position>("/api/admin/finance/reserve-policy", { method: "PUT", json: {
      opex_months: Number(p.opex_months), aging_0_30: Number(p.a), aging_31_90: Number(p.b), aging_90_plus: Number(p.c) } }));
    if (r) { setData(r); setPolicy(null); }
  };

  return (
    <Card title="Деньги и резерв" subtitle={data.note}>
      <ErrorBox error={action.error} />
      {data.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
      <div className="grid grid-3" style={{ marginBottom: 12 }}>
        <Stat label="Остаток денежных средств" value={data.cash ? formatRub(data.cash.amount_kopecks) : "не внесён"} hint={data.cash ? `на ${formatDate(data.cash.as_of)}` : "по выписке и кассе"} />
        <Stat label="Резерв" value={formatRub(data.reserve.total_kopecks)} hint="налоги + содержание бизнеса + возможные неплатежи" />
        <Stat label="Свободно для закупок" value={data.free_cash_kopecks === null ? "—" : formatRub(data.free_cash_kopecks)}
              tone={data.free_cash_kopecks !== null && data.free_cash_kopecks < 0 ? "danger" : "ok"} hint="остаток − резерв" />
      </div>
      <table><tbody>{data.reserve.items.map((i) => <tr key={i.code}><td>{i.title}<div className="small muted">{i.basis}</div></td><td className="num">{formatRub(i.amount_kopecks)}</td></tr>)}</tbody></table>
      <div className="actions" style={{ marginTop: 12 }}>
        {canCash ? (<><input value={cash} onChange={(e) => setCash(e.target.value)} placeholder="Остаток сегодня, ₽" style={{ maxWidth: 200 }} inputMode="decimal" />
          <button className="btn btn-sm" onClick={saveCash} disabled={action.busy}>Внести остаток</button></>) : null}
        {canPolicy && !policy ? <button className="btn btn-sm" onClick={() => setPolicy({ opex_months: String(data.policy.opex_months), a: String(data.policy.aging["0_30"]), b: String(data.policy.aging["31_90"]), c: String(data.policy.aging["90_plus"]) })}>Методика резерва</button> : null}
      </div>
      {policy ? (
        <div className="inline-form" style={{ marginTop: 10 }}>
          <p className="small muted">Управленческое решение владельца: сколько месяцев расходов держать в резерве и какую долю просроченного долга считать возможной потерей.</p>
          <div className="form-grid">
            <Field label="Месяцев расходов"><input value={policy.opex_months} onChange={(e) => setPolicy({ ...policy, opex_months: e.target.value })} /></Field>
            <Field label="Просрочка до 30 дн., %"><input value={policy.a} onChange={(e) => setPolicy({ ...policy, a: e.target.value })} /></Field>
            <Field label="31–90 дн., %"><input value={policy.b} onChange={(e) => setPolicy({ ...policy, b: e.target.value })} /></Field>
            <Field label="Более 90 дн., %"><input value={policy.c} onChange={(e) => setPolicy({ ...policy, c: e.target.value })} /></Field>
          </div>
          <div className="actions"><button className="btn btn-primary btn-sm" onClick={savePolicy}>Утвердить методику</button><button className="btn btn-sm" onClick={() => setPolicy(null)}>Отмена</button></div>
        </div>
      ) : data.policy.approved_at ? <p className="small muted" style={{ marginTop: 8 }}>Методика утверждена {data.policy.approved_by} {formatDate(data.policy.approved_at)}</p> : null}
    </Card>
  );
}

type ScenarioResult = { label: string; rows?: { month: string; base_kopecks?: number; scenario_kopecks?: number; diff_kopecks?: number; net_kopecks?: number; cumulative_kopecks?: number }[];
  diff_total_kopecks?: number; lost_total_kopecks?: number; need_kopecks?: number; shortfall_kopecks?: number | null; covered_in?: string | null;
  total_markup_kopecks?: number; max_cash_need_kopecks?: number; payback_month?: string | null; note?: string };

export function ScenariosCard({ contracts }: { contracts: { number: string; client: string }[] }) {
  const [kind, setKind] = useState("delay");
  const [selected, setSelected] = useState<string[]>([]);
  const [months, setMonths] = useState("1");
  const [fromMonth, setFromMonth] = useState(todayIso().slice(0, 7));
  const [purchase, setPurchase] = useState("");
  const [extra, setExtra] = useState("");
  const [deal, setDeal] = useState({ purchase: "1200000", sale: "1600000", down: "600000", term: "20", count: "2" });
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const action = useAction();

  const run = async () => {
    const k = (v: string) => rublesToKopecks(v) ?? 0;
    const body: Record<string, unknown> = { kind, contracts: selected };
    if (kind === "delay") body.delay_months = Number(months);
    if (kind === "defaults") body.from_month = `${fromMonth}-01`;
    if (kind === "next_car") { body.purchase_kopecks = k(purchase); body.extra_kopecks = k(extra); }
    if (kind === "deals") body.deals = Array.from({ length: Number(deal.count) || 1 }, () => ({ purchase_kopecks: k(deal.purchase), sale_kopecks: k(deal.sale), down_kopecks: k(deal.down), term_months: Number(deal.term) }));
    const r = await action.run(() => api<ScenarioResult>("/api/admin/finance/scenario", { method: "POST", json: body }));
    if (r) setResult(r);
  };

  return (
    <Card title="Сценарии" subtitle="Прогнозы для решений — не фактическая прибыль">
      <ErrorBox error={action.error} />
      <div className="tabs">
        {[["delay", "Задержка платежей"], ["defaults", "Неплательщики"], ["next_car", "Капитал на следующий автомобиль"], ["deals", "Несколько продаж"]].map(([k, t]) => (
          <button key={k} className={kind === k ? "active" : ""} onClick={() => { setKind(k); setResult(null); }}>{t}</button>
        ))}
      </div>
      {kind === "delay" || kind === "defaults" ? (
        <div className="inline-form">
          <div className="actions">{contracts.map((c) => (
            <label key={c.number} className="check small"><input type="checkbox" checked={selected.includes(c.number)} onChange={(e) => setSelected(e.target.checked ? [...selected, c.number] : selected.filter((x) => x !== c.number))} />№ {c.number} · {c.client}</label>
          ))}{!contracts.length ? <span className="small muted">Действующих договоров нет</span> : null}</div>
          {kind === "delay" ? <Field label="На сколько месяцев задерживаются платежи"><input type="number" min={1} max={24} value={months} onChange={(e) => setMonths(e.target.value)} style={{ maxWidth: 120 }} /></Field>
            : <Field label="Перестают платить с месяца"><input type="month" value={fromMonth} onChange={(e) => setFromMonth(e.target.value)} style={{ maxWidth: 200 }} /></Field>}
        </div>
      ) : kind === "next_car" ? (
        <div className="form-grid">
          <Field label="Закупочная цена автомобиля, ₽"><input value={purchase} onChange={(e) => setPurchase(e.target.value)} inputMode="decimal" /></Field>
          <Field label="Подготовка, оформление и прочее, ₽"><input value={extra} onChange={(e) => setExtra(e.target.value)} inputMode="decimal" /></Field>
        </div>
      ) : (
        <div className="form-grid">
          <Field label="Закупка одного автомобиля, ₽"><input value={deal.purchase} onChange={(e) => setDeal({ ...deal, purchase: e.target.value })} /></Field>
          <Field label="Цена продажи, ₽"><input value={deal.sale} onChange={(e) => setDeal({ ...deal, sale: e.target.value })} /></Field>
          <Field label="Первоначальный взнос, ₽"><input value={deal.down} onChange={(e) => setDeal({ ...deal, down: e.target.value })} /></Field>
          <Field label="Срок, мес."><input value={deal.term} onChange={(e) => setDeal({ ...deal, term: e.target.value })} /></Field>
          <Field label="Количество таких продаж"><input value={deal.count} onChange={(e) => setDeal({ ...deal, count: e.target.value })} /></Field>
        </div>
      )}
      <div style={{ marginTop: 10 }}><button className="btn btn-primary btn-sm" onClick={run} disabled={action.busy}>Рассчитать прогноз</button></div>
      {result ? (
        <div style={{ marginTop: 12 }}>
          <Notice tone="info" title={result.label}>{result.note ?? "Расчёт по графикам действующих договоров"}</Notice>
          {result.diff_total_kopecks !== undefined ? <p>Изменение поступлений за горизонт: <strong>{formatRub(result.diff_total_kopecks)}</strong>{result.lost_total_kopecks !== undefined ? ` · всего не поступит ${formatRub(result.lost_total_kopecks)}` : ""}</p> : null}
          {result.need_kopecks !== undefined ? <p>Нужно {formatRub(result.need_kopecks)} · не хватает {result.shortfall_kopecks === null ? "— (остаток не внесён)" : formatRub(result.shortfall_kopecks)} · закроется: {result.covered_in ? (result.covered_in === "сейчас" ? "уже сейчас" : formatMonth(result.covered_in)) : "не в пределах года"}</p> : null}
          {result.total_markup_kopecks !== undefined ? <p>Наценка по сделкам {formatRub(result.total_markup_kopecks)} · максимальная потребность в деньгах {formatRub(result.max_cash_need_kopecks)} · окупаемость вложений: {result.payback_month ? formatMonth(result.payback_month) : "за пределами 3 лет"}</p> : null}
          {result.rows ? (
            <div className="table-wrap" style={{ maxHeight: 280, overflowY: "auto" }}>
              <table><tbody>{result.rows.map((r) => (
                <tr key={r.month}><td className="small">{formatMonth(r.month)}</td>
                  {r.base_kopecks !== undefined ? <><td className="num">{formatRub(r.base_kopecks)}</td><td className="num">{formatRub(r.scenario_kopecks)}</td><td className="num" style={{ color: (r.diff_kopecks ?? 0) < 0 ? "var(--danger)" : undefined }}>{formatRub(r.diff_kopecks)}</td></>
                    : <><td className="num">{formatRub(r.net_kopecks)}</td><td className="num">{formatRub(r.cumulative_kopecks)}</td></>}
                </tr>
              ))}</tbody></table>
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

type Group = { group: string; contracts: number; price_kopecks: number; markup_kopecks: number; markup_percent: number | null; received_kopecks: number; overdue_share: number };

export function ProfitabilityCard() {
  const { data, error } = useApi<{ groups: Record<string, Group[]>; note: string }>("/api/admin/finance/profitability");
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const all = Object.values(data.groups).flat();
  return (
    <Card title="Рентабельность" subtitle={data.note} flush>
      {!all.length ? <div className="empty">Нет подписанных договоров</div> : (
        <table>
          <thead><tr><th>Группа</th><th className="num">Договоров</th><th className="num">Наценка</th><th className="num">Наценка, %</th><th className="num">Поступило</th><th className="num">Просрочка</th></tr></thead>
          <tbody>{all.map((g) => (
            <tr key={g.group}><td>{g.group}</td><td className="num">{g.contracts}</td><td className="num">{formatRub(g.markup_kopecks)}</td>
              <td className="num">{g.markup_percent ?? "—"}</td><td className="num">{formatRub(g.received_kopecks)}</td><td className="num">{g.overdue_share}%</td></tr>
          ))}</tbody>
        </table>
      )}
    </Card>
  );
}
