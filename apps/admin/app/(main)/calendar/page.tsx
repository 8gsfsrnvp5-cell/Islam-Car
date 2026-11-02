"use client";

import { ROW_STATUS, formatDate, formatMonth, formatRub } from "@islamic-car/shared";
import Link from "next/link";
import { useState } from "react";

import { Card, Empty, ErrorBox, Loading, PageHead, Stat, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/useApi";

type Calendar = {
  month: string; today: string; expected_kopecks: number; received_kopecks: number; remaining_kopecks: number;
  items: { contract_id: string; number: string; client: string; car: string; seq: number; kind: string; due_date: string;
    amount_kopecks: number; paid_kopecks: number; remaining_kopecks: number; status: string }[];
};

function shift(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function CalendarPage() {
  const [month, setMonth] = useState<string | null>(null);
  const { data, error, loading } = useApi<Calendar>(`/api/admin/calendar${month ? `?month=${month}` : ""}`);
  const current = data?.month ?? month;

  const byDate = new Map<string, Calendar["items"]>();
  for (const it of data?.items ?? []) byDate.set(it.due_date, [...(byDate.get(it.due_date) ?? []), it]);

  return (
    <>
      <PageHead title="Календарь поступлений" subtitle="Платежи по графикам действующих договоров"
                actions={current ? (
                  <>
                    <button className="btn btn-sm" onClick={() => setMonth(shift(current, -1))}>← Предыдущий</button>
                    <strong style={{ minWidth: 140, textAlign: "center" }}>{formatMonth(current)}</strong>
                    <button className="btn btn-sm" onClick={() => setMonth(shift(current, 1))}>Следующий →</button>
                  </>
                ) : null} />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : data ? (
        <>
          <div className="grid grid-3" style={{ marginBottom: 16 }}>
            <Stat label="Ожидается по графику" value={formatRub(data.expected_kopecks)} />
            <Stat label="Уже поступило по этим платежам" value={formatRub(data.received_kopecks)} tone="ok" />
            <Stat label="Осталось получить" value={formatRub(data.remaining_kopecks)} />
          </div>
          {!data.items.length ? <Card><Empty>В этом месяце платежей по графикам нет</Empty></Card> : (
            [...byDate.entries()].map(([d, items]) => (
              <Card key={d} title={formatDate(d)} subtitle={d === data.today ? "Сегодня" : undefined} flush>
                <table>
                  <tbody>
                    {items.map((it) => (
                      <tr key={`${it.contract_id}-${it.seq}`}>
                        <td style={{ width: 160 }}><Link href={`/contracts/${it.contract_id}`}>№ {it.number}</Link></td>
                        <td>{it.client}<div className="small muted">{it.car} · {it.seq === 0 ? "первоначальный взнос" : `платёж ${it.seq}`}</div></td>
                        <td className="num">{formatRub(it.amount_kopecks)}{it.paid_kopecks && it.remaining_kopecks ? <div className="small muted">осталось {formatRub(it.remaining_kopecks)}</div> : null}</td>
                        <td style={{ width: 150 }}><StatusBadge status={it.status} labels={ROW_STATUS} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            ))
          )}
        </>
      ) : null}
    </>
  );
}
