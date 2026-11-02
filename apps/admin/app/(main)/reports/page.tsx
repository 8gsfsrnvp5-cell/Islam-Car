"use client";

import Link from "next/link";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Card, Field, Notice, PageHead } from "@/components/ui";

export default function ReportsPage() {
  const can = useCan("reports.read");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const params = new URLSearchParams();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);

  if (!can) return <><PageHead title="Отчёты" /><Notice tone="warn">Недостаточно прав для выгрузки отчётов.</Notice></>;

  return (
    <>
      <PageHead title="Отчёты" subtitle="Выгрузки для Excel: XLSX (числа и даты как значения) или CSV (разделитель «;», UTF-8)" />
      <div className="grid grid-2">
        <Card title="Реестр договоров" subtitle="Все подписанные и исполненные договоры с остатками на сегодня">
          <div className="actions">
            <a className="btn btn-primary" href="/api/admin/reports/contracts.xlsx">Excel (XLSX)</a>
            <a className="btn" href="/api/admin/reports/contracts.csv">CSV</a>
          </div>
        </Card>
        <Card title="Журнал платежей" subtitle="Все поступления, включая сторнированные — с причинами">
          <div className="form-grid" style={{ marginBottom: 12 }}>
            <Field label="С"><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="По"><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
          <div className="actions">
            <a className="btn btn-primary" href={`/api/admin/reports/payments.xlsx?${params}`}>Excel (XLSX)</a>
            <a className="btn" href={`/api/admin/reports/payments.csv?${params}`}>CSV</a>
          </div>
        </Card>
        <Card title="Поступления по банковским выпискам" subtitle="Все загруженные поступления с решениями сотрудников">
          <a className="btn btn-primary" href="/api/admin/reports/bank.xlsx">Excel (XLSX)</a>
        </Card>
        <Card title="Аналитика и прогноз" subtitle="План и факт, просрочка, продажи, заявки, прогноз поступлений — шесть листов">
          <div className="actions">
            <a className="btn btn-primary" href="/api/admin/analytics.xlsx">Excel (XLSX)</a>
            <Link className="btn" href="/analytics">Открыть аналитику</Link>
          </div>
        </Card>
      </div>
      <Notice tone="info">Рентабельность по маркам, срокам и взносам — в разделе <Link href="/finance">«Финансы»</Link>.</Notice>
    </>
  );
}
