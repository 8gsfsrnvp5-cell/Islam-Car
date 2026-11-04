"use client";

import { CONTRACT_STATUS, type StaffContract, formatDate, formatRub } from "@islamic-car/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Loading, PageHead, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/useApi";

const FILTERS = ["", "draft", "signed", "completed", "cancelled"];

export default function ContractsPage() {
  const router = useRouter();
  const canWrite = useCan("contracts.write");
  const [status, setStatus] = useState("");
  const { data, error, loading } = useApi<StaffContract[]>(`/api/admin/contracts${status ? `?status=${status}` : ""}`);

  return (
    <>
      <PageHead title="Договоры" subtitle="Купля-продажа автомобилей с оплатой по графику, без процентов за рассрочку"
                actions={canWrite ? <Link className="btn btn-primary" href="/contracts/new">Новый договор</Link> : null} />
      <div className="tabs">
        {FILTERS.map((s) => (
          <button key={s || "all"} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>{s ? CONTRACT_STATUS[s] : "Все"}</button>
        ))}
      </div>
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.length ? <Empty>Договоров нет</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Договор</th><th>Покупатель</th><th>Автомобиль</th><th className="num">Цена</th><th className="num">Оплачено</th>
                  <th className="num">Остаток</th><th>Следующий платёж</th><th>Статус</th></tr>
              </thead>
              <tbody>
                {data.map((c) => (
                  <tr key={c.id} className="clickable" onClick={() => router.push(`/contracts/${c.id}`)}>
                    <td><strong>{c.number ? `№ ${c.number}` : "Черновик"}</strong><div className="small muted">{formatDate(c.signed_at ?? c.contract_date)}</div></td>
                    <td>{c.client.full_name}</td>
                    <td>{c.car.title}</td>
                    <td className="num">{formatRub(c.sale_price_kopecks)}</td>
                    <td className="num">{c.ledger ? formatRub(c.ledger.paid_kopecks) : "—"}</td>
                    <td className="num">
                      {c.ledger ? formatRub(c.ledger.outstanding_kopecks) : "—"}
                      {c.ledger?.overdue_kopecks ? <div><Badge tone="danger">просрочка {formatRub(c.ledger.overdue_kopecks)}</Badge></div> : null}
                    </td>
                    <td className="small">{c.ledger?.next_due_date ? <>{formatDate(c.ledger.next_due_date)}<div className="muted">{formatRub(c.ledger.next_due_kopecks)}</div></> : "—"}</td>
                    <td><StatusBadge status={c.status} labels={CONTRACT_STATUS} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
