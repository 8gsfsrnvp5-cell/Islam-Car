"use client";

import { ROW_STATUS, THREAD_STATUS, THREAD_TOPIC, type Thread, api, formatDate, formatDateTime, formatRub, label } from "@islamic-car/shared";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

export default function ThreadPage() {
  const { id } = useParams<{ id: string }>();
  const canWrite = useCan("support.write");
  const { data: t, error, setData } = useApi<Thread>(`/api/admin/threads/${id}`, 10000);
  const [body, setBody] = useState("");
  const action = useAction();

  if (!t) return error ? <ErrorBox error={error} /> : <Loading />;

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const r = await action.run(() => api<Thread>(`/api/admin/threads/${id}/messages`, { method: "POST", json: { body } }));
    if (r) { setData({ ...r, contract: t!.contract }); setBody(""); }
  }
  async function close() {
    const r = await action.run(() => api<Thread>(`/api/admin/threads/${id}/close`, { method: "POST" }));
    if (r) setData({ ...r, contract: t!.contract });
  }

  const k = t.contract;
  return (
    <>
      <PageHead title={t.subject}
                subtitle={<>{label(THREAD_TOPIC, t.topic)} · <Link href={`/clients/${t.client?.id}`}>{t.client?.full_name}</Link> · <StatusBadge status={t.status} labels={THREAD_STATUS} /></>}
                actions={canWrite && t.status !== "closed" ? <button className="btn" onClick={close}>Закрыть обращение</button> : null} />
      <ErrorBox error={action.error} />
      {["schedule_change", "payment_difficulty", "early_repayment"].includes(t.topic) ? (
        <Notice tone="info">
          Запрос покупателя не меняет договор и график автоматически. Изменение оформляется дополнительным соглашением
          (конструктор документов — версия 2) после решения ответственного лица. Проценты за отсрочку не начисляются.
        </Notice>
      ) : null}
      <div className="split">
        <Card title="Переписка">
          <div className="chat">
            {t.messages?.map((m) => (
              <div key={m.id} className={`msg ${m.from_staff ? "staff" : ""}`}>
                <div className="meta">{m.from_staff ? `${m.author} (сотрудник)` : t.client?.full_name} · {formatDateTime(m.created_at)}</div>
                {m.body}
              </div>
            ))}
          </div>
          {canWrite && t.status !== "closed" ? (
            <form onSubmit={send} style={{ marginTop: 12 }} className="grid">
              <textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Ответ покупателю" required />
              <div><button className="btn btn-primary" disabled={action.busy}>Отправить ответ</button></div>
            </form>
          ) : null}
        </Card>
        <div>
          {k ? (
            <Card title={`Договор № ${k.number}`} subtitle={k.car.title}>
              <dl className="kv">
                <dt>Цена</dt><dd>{formatRub(k.sale_price_kopecks)}</dd>
                <dt>Оплачено</dt><dd>{formatRub(k.ledger?.paid_kopecks)}</dd>
                <dt>Остаток</dt><dd>{formatRub(k.ledger?.outstanding_kopecks)}</dd>
                <dt>Просрочено</dt><dd>{formatRub(k.ledger?.overdue_kopecks)}</dd>
                <dt>Следующий платёж</dt><dd>{k.ledger?.next_due_date ? `${formatRub(k.ledger.next_due_kopecks)} до ${formatDate(k.ledger.next_due_date)}` : "—"}</dd>
              </dl>
              <div className="table-wrap" style={{ maxHeight: 300, overflowY: "auto", marginTop: 10 }}>
                <table>
                  <tbody>
                    {k.ledger?.rows?.map((r) => (
                      <tr key={r.seq}><td>{formatDate(r.due_date)}</td><td className="num">{formatRub(r.amount_kopecks)}</td>
                        <td><StatusBadge status={r.status} labels={ROW_STATUS} /></td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Link className="btn btn-sm" href={`/contracts/${k.id}`} style={{ marginTop: 10 }}>Открыть договор</Link>
            </Card>
          ) : <Notice>Обращение не связано с договором.</Notice>}
        </div>
      </div>
    </>
  );
}
