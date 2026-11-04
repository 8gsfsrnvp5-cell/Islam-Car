"use client";

import { formatRub } from "@islamic-car/shared";
import { useState } from "react";

import { BarList, ColumnChart, ORDINAL, SERIES, monthLabel, useTableToggle } from "@/components/Charts";
import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice, PageHead, Stat } from "@/components/ui";
import { useApi } from "@/lib/useApi";

type Analytics = {
  today: string; months: string[];
  kpi: { receivables_kopecks: number; overdue_kopecks: number; overdue_share: number | null; collection_rate_3m: number | null;
    contracts_overdue: number; applications: number; conversion: number | null };
  monthly: { month: string; planned_kopecks: number; collected_kopecks: number; collection_rate: number | null;
    by_source: Record<string, number> }[];
  sales: { month: string; count: number; volume_kopecks: number; markup_kopecks?: number }[];
  aging: { code: string; title: string; amount_kopecks: number; contracts: number }[];
  applications: { month: string; count: number }[];
  funnel: { code: string; title: string; count: number; share: number | null }[];
  applications_closed_without_deal: number;
  forecast: { label: string; rows: { month: string; scheduled_kopecks: number; risk_adjusted_kopecks: number }[];
    overdue_recovery_kopecks: number; method: string; warnings: string[]; note: string };
  notes: string[];
};

const pct = (v: number | null) => (v === null ? "—" : `${v.toLocaleString("ru-RU")}%`);
const SOURCES: [string, string][] = [["staff", "Сотрудник"], ["bank_statement", "Выписка"], ["provider", "Онлайн"]];

function PlanFact({ a }: { a: Analytics }) {
  const [table, toggle] = useTableToggle();
  return (
    <Card title="План и факт поступлений" subtitle="По графикам договоров и подтверждённым платежам" actions={toggle}>
      {table ? (
        <div className="table-wrap"><table>
          <thead><tr><th>Месяц</th><th className="num">По графику</th><th className="num">Поступило</th><th className="num">Собираемость</th>
            {SOURCES.map(([k, t]) => <th key={k} className="num">{t}</th>)}</tr></thead>
          <tbody>{a.monthly.map((m) => (
            <tr key={m.month}><td>{monthLabel(m.month)}</td><td className="num">{formatRub(m.planned_kopecks)}</td>
              <td className="num">{formatRub(m.collected_kopecks)}</td><td className="num">{pct(m.collection_rate)}</td>
              {SOURCES.map(([k]) => <td key={k} className="num">{formatRub(m.by_source[k] ?? 0)}</td>)}</tr>
          ))}</tbody>
        </table></div>
      ) : (
        <ColumnChart categories={a.monthly.map((m) => m.month)} format={formatRub}
                     series={[
                       { key: "plan", name: "По графику", color: SERIES[0], values: a.monthly.map((m) => m.planned_kopecks) },
                       { key: "fact", name: "Поступило", color: SERIES[1], values: a.monthly.map((m) => m.collected_kopecks) },
                     ]}
                     extra={(i) => <div className="small muted" style={{ marginTop: 4 }}>Собираемость: {pct(a.monthly[i].collection_rate)}</div>} />
      )}
    </Card>
  );
}

function Forecast({ a }: { a: Analytics }) {
  const [table, toggle] = useTableToggle();
  const fc = a.forecast;
  return (
    <Card title={<>Прогноз поступлений на 12 месяцев<span className="forecast-tag">{fc.label}</span></>}
          subtitle={fc.note} actions={toggle}>
      {fc.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
      {table ? (
        <table>
          <thead><tr><th>Месяц</th><th className="num">По графику</th><th className="num">С учётом риска</th></tr></thead>
          <tbody>{fc.rows.map((r) => (
            <tr key={r.month}><td>{monthLabel(r.month)}</td><td className="num">{formatRub(r.scheduled_kopecks)}</td>
              <td className="num">{formatRub(r.risk_adjusted_kopecks)}</td></tr>
          ))}</tbody>
        </table>
      ) : (
        <ColumnChart categories={fc.rows.map((r) => r.month)} format={formatRub}
                     series={[
                       { key: "scheduled", name: "По графику", color: SERIES[0], values: fc.rows.map((r) => r.scheduled_kopecks) },
                       { key: "risk", name: "С учётом риска", color: SERIES[1], values: fc.rows.map((r) => r.risk_adjusted_kopecks) },
                     ]} />
      )}
      <p className="small" style={{ marginTop: 10 }}>Возможное погашение просроченных сумм (без привязки к месяцу):{" "}
        <strong>{formatRub(fc.overdue_recovery_kopecks)}</strong></p>
      <p className="small muted">{fc.method}</p>
    </Card>
  );
}

export default function AnalyticsPage() {
  const can = useCan("reports.read");
  const [months, setMonths] = useState(12);
  const { data: a, error, loading } = useApi<Analytics>(can ? `/api/admin/analytics?months=${months}` : null);
  const finance = useCan("finance.read");

  if (!can) return <><PageHead title="Аналитика и прогноз" /><Notice tone="warn">Недостаточно прав.</Notice></>;
  return (
    <>
      <PageHead title="Аналитика и прогноз" subtitle="Только подтверждённые платежи и действующие графики. Прогноз помечен как прогноз"
                actions={<a className="btn btn-sm" href={`/api/admin/analytics.xlsx?months=${months}`}>Выгрузить в Excel</a>} />
      <div className="actions" style={{ marginBottom: 12 }}>
        <span className="small muted">Период:</span>
        {[6, 12, 24].map((m) => (
          <button key={m} className={`btn btn-sm ${months === m ? "btn-primary" : ""}`} onClick={() => setMonths(m)}>{m} мес.</button>
        ))}
      </div>
      <ErrorBox error={error} />
      {loading && !a ? <Loading /> : a ? (
        <div style={{ opacity: loading ? 0.6 : 1 }}>
          <div className="grid grid-4" style={{ marginBottom: 16 }}>
            <Stat label="Дебиторская задолженность" value={formatRub(a.kpi.receivables_kopecks)} />
            <Stat label="Просрочено" value={formatRub(a.kpi.overdue_kopecks)} hint={`${pct(a.kpi.overdue_share)} долга · договоров: ${a.kpi.contracts_overdue}`}
                  tone={a.kpi.overdue_kopecks ? "danger" : undefined} />
            <Stat label="Собираемость за 3 закрытых месяца" value={pct(a.kpi.collection_rate_3m)} />
            <Stat label="Конверсия заявок в договор" value={pct(a.kpi.conversion)} hint={`заявок за период: ${a.kpi.applications}`} />
          </div>
          <PlanFact a={a} />
          <div className="grid grid-2">
            <Card title="Просрочка по срокам" subtitle="Сумма просроченных платежей; в скобках — договоров по самой старой просрочке">
              <BarList format={formatRub}
                       rows={a.aging.map((b, i) => ({ label: b.title, value: b.amount_kopecks, color: ORDINAL[i], note: `договоров: ${b.contracts}` }))} />
              <p className="small muted" style={{ marginTop: 10 }}>Проценты и штрафы за просрочку не начисляются.</p>
            </Card>
            <Card title="Воронка заявок" subtitle={`Заявки за ${months} мес. Закрыты без договора: ${a.applications_closed_without_deal}`}>
              <BarList format={(v) => v.toLocaleString("ru-RU")}
                       rows={a.funnel.map((f) => ({ label: f.title, value: f.count, color: SERIES[0], note: f.share === null ? undefined : pct(f.share) }))} />
            </Card>
          </div>
          <Forecast a={a} />
          <Card title="Продажи по месяцам" subtitle="Подписанные договоры" flush>
            <table>
              <thead><tr><th>Месяц</th><th className="num">Договоров</th><th className="num">Объём</th>{finance ? <th className="num">Наценка</th> : null}
                <th className="num">Заявок</th></tr></thead>
              <tbody>{a.sales.map((s, i) => (
                <tr key={s.month}><td>{monthLabel(s.month)}</td><td className="num">{s.count}</td><td className="num">{formatRub(s.volume_kopecks)}</td>
                  {finance ? <td className="num">{formatRub(s.markup_kopecks ?? 0)}</td> : null}
                  <td className="num">{a.applications[i]?.count ?? 0}</td></tr>
              ))}</tbody>
            </table>
          </Card>
          <Notice tone="info" title="Как считается">
            <ul style={{ margin: 0, paddingLeft: 18 }}>{a.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          </Notice>
        </div>
      ) : null}
    </>
  );
}
