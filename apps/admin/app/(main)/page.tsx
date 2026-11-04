"use client";

import { formatDate, formatMonth, formatRub } from "@islamic-car/shared";
import Link from "next/link";
import { useState } from "react";

import { Card, ErrorBox, Loading, Notice, PageHead, Stat } from "@/components/ui";
import { useApi } from "@/lib/useApi";

type Dashboard = {
  today: string;
  period: { from: string; to: string };
  operations: Record<string, number>;
  money: {
    contracted_volume_kopecks: number; down_payments_contracted_kopecks: number; down_payments_received_kopecks: number;
    receivables_kopecks: number; overdue_kopecks: number; cash_received_period_kopecks: number;
    upcoming_30d_kopecks: number; forecast: { month: string; expected_kopecks: number }[];
  };
  problem_deals: { contract_id: string; number: string; client: string; car: string; overdue_kopecks: number;
    overdue_items: number; oldest_overdue_date: string; days_overdue: number }[];
  finance?: {
    purchase_cost_sold_kopecks: number; gross_markup_kopecks: number; inventory_cost_kopecks: number;
    operating_expenses_period_kopecks: number; markup_signed_in_period_kopecks: number;
    estimated_result_period_kopecks: number; estimated_result_note: string;
    taxes: { status: string; message: string };
  };
};

export default function DashboardPage() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const qs = from && to ? `?date_from=${from}&date_to=${to}` : "";
  const { data, error, loading } = useApi<Dashboard>(`/api/admin/dashboard${qs}`, 15000);

  if (loading && !data) return <Loading />;
  if (!data) return <ErrorBox error={error} />;
  const o = data.operations;
  const m = data.money;
  const f = data.finance;
  const maxForecast = Math.max(1, ...m.forecast.map((x) => x.expected_kopecks));

  return (
    <>
      <PageHead
        title="Операционный центр"
        subtitle={`Сегодня ${formatDate(data.today)} · период ${formatDate(data.period.from)} — ${formatDate(data.period.to)}`}
        actions={
          <>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Начало периода" />
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Конец периода" />
            {qs ? <button className="btn btn-sm" onClick={() => { setFrom(""); setTo(""); }}>Текущий месяц</button> : null}
          </>
        }
      />
      <ErrorBox error={error} />

      <div className="grid grid-4">
        <Stat label="Клиенты" value={o.clients} />
        <Stat label="Активные договоры" value={o.active_contracts} hint={`Исполнено: ${o.completed_contracts} · черновиков: ${o.draft_contracts}`} />
        <Stat label="Продано автомобилей" value={o.cars_sold} hint={`В наличии: ${o.cars_in_stock} · в закупке: ${o.cars_purchasing}`} />
        <Stat label="Проблемные сделки" value={o.problem_deals} tone={o.problem_deals ? "danger" : undefined} hint="Договоры с просрочкой" />
        <Link href="/applications" className="stat"><div className="label">Новые заявки</div><div className="value">{o.new_applications}</div><div className="hint">Ожидают обработки</div></Link>
        <Link href="/payments" className="stat"><div className="label">Сообщения «Я оплатил»</div><div className="value">{o.pending_payment_reports}</div><div className="hint">Нужна сверка с банком</div></Link>
        <Link href="/support" className="stat"><div className="label">Открытые обращения</div><div className="value">{o.open_threads}</div><div className="hint">Ждут ответа</div></Link>
      </div>

      <div className="section-title"><h2>Деньги и задолженность</h2><span>Договорной объём, поступления и долг — разные величины и не складываются</span></div>
      <div className="grid grid-4">
        <Stat label="Объём заключённых договоров" value={formatRub(m.contracted_volume_kopecks)} hint="Сумма цен продажи. Это не деньги на счёте." />
        <Stat label="Первоначальные взносы" value={formatRub(m.down_payments_received_kopecks)} hint={`Получено из ${formatRub(m.down_payments_contracted_kopecks)} по договорам`} />
        <Stat label="Дебиторская задолженность" value={formatRub(m.receivables_kopecks)} hint="Ещё не получено по действующим договорам" />
        <Stat label="Просроченная задолженность" value={formatRub(m.overdue_kopecks)} tone={m.overdue_kopecks ? "danger" : undefined} hint="Без процентов и штрафов" />
        <Stat label="Поступило за период" value={formatRub(m.cash_received_period_kopecks)} tone="ok" hint="Только подтверждённые сотрудником платежи" />
        <Stat label="Ожидается в ближайшие 30 дней" value={formatRub(m.upcoming_30d_kopecks)} hint="По графикам платежей" />
      </div>

      {f ? (
        <>
          <div className="section-title"><h2>Финансовый результат</h2><span>Управленческая оценка, не бухгалтерская отчётность</span></div>
          <div className="grid grid-4">
            <Stat label="Закупочная стоимость проданных" value={formatRub(f.purchase_cost_sold_kopecks)} />
            <Stat label="Валовая торговая наценка" value={formatRub(f.gross_markup_kopecks)} hint="По всем заключённым договорам. Это не прибыль и не деньги." />
            <Stat label="Автомобили на складе (себестоимость)" value={formatRub(f.inventory_cost_kopecks)} hint="Деньги, вложенные в непроданные автомобили" />
            <Stat label="Операционные расходы за период" value={formatRub(f.operating_expenses_period_kopecks)} hint="Внесённые в раздел «Финансы»" />
            <Stat label="Оценочный результат периода" value={formatRub(f.estimated_result_period_kopecks)}
                  tone={f.estimated_result_period_kopecks < 0 ? "danger" : undefined} hint={f.estimated_result_note} />
          </div>
          <Notice tone="warn" title="Налоговые обязательства">{f.taxes.message}</Notice>
        </>
      ) : null}

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Card title="Прогноз поступлений" subtitle="По графикам действующих договоров. Прогноз, а не факт: просроченные суммы сюда не входят.">
          <div className="bars">
            {m.forecast.map((x) => (
              <div className="bar-row" key={x.month}>
                <span>{formatMonth(x.month)}</span>
                <div className="bar"><i style={{ width: `${(x.expected_kopecks / maxForecast) * 100}%` }} /></div>
                <span className="right">{formatRub(x.expected_kopecks)}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Проблемные сделки" subtitle="Договоры с неоплаченными просроченными платежами" flush>
          {data.problem_deals.length === 0 ? <div className="empty">Просрочек нет</div> : (
            <table>
              <thead><tr><th>Договор</th><th>Покупатель</th><th className="num">Просрочено</th><th className="num">Дней</th></tr></thead>
              <tbody>
                {data.problem_deals.map((d) => (
                  <tr key={d.contract_id}>
                    <td><Link href={`/contracts/${d.contract_id}`}>№ {d.number}</Link><div className="small muted">{d.car}</div></td>
                    <td>{d.client}</td>
                    <td className="num">{formatRub(d.overdue_kopecks)}</td>
                    <td className="num">{d.days_overdue}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  );
}
