"use client";

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
      <PageHead title="Отчёты" subtitle="Выгрузки для Excel (CSV, разделитель «;», кодировка UTF-8)" />
      <div className="grid grid-2">
        <Card title="Реестр договоров" subtitle="Все подписанные и исполненные договоры с остатками на сегодня">
          <a className="btn btn-primary" href="/api/admin/reports/contracts.csv">Скачать contracts.csv</a>
        </Card>
        <Card title="Журнал платежей" subtitle="Все поступления, включая сторнированные — с причинами">
          <div className="form-grid" style={{ marginBottom: 12 }}>
            <Field label="С"><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="По"><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
          <a className="btn btn-primary" href={`/api/admin/reports/payments.csv?${params}`}>Скачать payments.csv</a>
        </Card>
      </div>
      <Notice tone="info">
        Аналитика рентабельности по типам автомобилей и договоров, управленческие прогнозы и выгрузка в Excel (XLSX) — версии 3–4.
      </Notice>
    </>
  );
}
