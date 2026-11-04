"use client";

import { APPLICATION_STATUS, CONTRACT_STATUS, type ClientContract, type PublicApplication, formatDate, formatDateTime, formatRub } from "@islamic-car/shared";
import Link from "next/link";

import { useClientApi } from "@/lib/useClientApi";

export default function CabinetHome() {
  const contracts = useClientApi<ClientContract[]>("/api/client/contracts", 30000);
  const apps = useClientApi<PublicApplication[]>("/api/client/applications");

  return (
    <>
      <h1>Мои договоры</h1>
      {contracts.error ? <div className="notice danger">{contracts.error}</div> : null}
      {!contracts.data ? <p>Загрузка…</p> : !contracts.data.length ? (
        <div className="panel">Действующих договоров пока нет.</div>
      ) : contracts.data.map((c) => (
        <div className="panel" key={c.id}>
          <div className="actions" style={{ justifyContent: "space-between" }}>
            <div>
              <h2 style={{ marginBottom: 2 }}>{c.car.title}</h2>
              <div className="small muted">Договор № {c.number} от {formatDate(c.signed_at)} · VIN {c.car.vin}</div>
            </div>
            <span className={`badge ${c.status === "completed" ? "ok" : ""}`}>{CONTRACT_STATUS[c.status]}</span>
          </div>
          <div className="stats" style={{ marginTop: 14 }}>
            <div className="stat"><span>Цена договора</span><strong>{formatRub(c.ledger.total_kopecks)}</strong></div>
            <div className="stat ok"><span>Оплачено</span><strong>{formatRub(c.ledger.paid_kopecks)}</strong></div>
            <div className="stat"><span>Остаток</span><strong>{formatRub(c.ledger.outstanding_kopecks)}</strong></div>
            <div className={`stat ${c.ledger.overdue_kopecks ? "danger" : ""}`}>
              <span>{c.ledger.overdue_kopecks ? "Просрочено" : "Следующий платёж"}</span>
              <strong>{c.ledger.overdue_kopecks ? formatRub(c.ledger.overdue_kopecks) : c.ledger.next_due_date ? formatRub(c.ledger.next_due_kopecks) : "—"}</strong>
              {!c.ledger.overdue_kopecks && c.ledger.next_due_date ? <span>до {formatDate(c.ledger.next_due_date)}</span> : null}
            </div>
          </div>
          <Link href={`/cabinet/contracts/${c.id}`} className="btn btn-primary btn-sm">График и платежи</Link>
        </div>
      ))}

      {apps.data?.length ? (
        <div className="panel">
          <h2>Мои заявки</h2>
          {apps.data.map((a, i) => (
            <div className="list-item" key={i}>
              <div>{a.car_title ?? a.wanted}<div className="small muted">{formatDateTime(a.created_at)}{a.public_message ? ` · ${a.public_message}` : ""}</div></div>
              <span className="badge">{APPLICATION_STATUS[a.status] ?? a.status}</span>
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}
