"use client";

import {
  INTENT_STATUS, PAYMENT_METHOD, PAYMENT_SOURCE, PAYMENT_STATUS, type Payment, type PaymentIntent, type PaymentReport, api,
  formatDate, formatDateTime, formatRub, label,
} from "@islamic-car/shared";
import Link from "next/link";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

function OnlineIntents() {
  const canConfirm = useCan("payments.confirm");
  const intents = useApi<PaymentIntent[]>("/api/admin/payment-intents", 15000);
  const action = useAction();
  const open = (intents.data ?? []).filter((i) => i.status === "needs_review" || i.status === "pending");
  if (!intents.data?.length) return null;
  const resync = async (id: string) => {
    if (await action.run(() => api(`/api/admin/payment-intents/${id}/sync`, { method: "POST" }))) intents.reload();
  };
  return (
    <Card title="Онлайн-оплаты" subtitle="Платёж учитывается автоматически только после проверки статуса у платёжного сервиса" flush>
      <ErrorBox error={intents.error ?? action.error} />
      {!open.length ? <Empty>Незавершённых и требующих проверки оплат нет</Empty> : (
        <table>
          <thead><tr><th>Создана</th><th>Договор</th><th className="num">Сумма</th><th>Сервис</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            {open.map((i) => (
              <tr key={i.id}>
                <td className="small">{formatDateTime(i.created_at)}</td>
                <td><Link href={`/contracts/${i.contract_id}`}>№ {i.contract_number}</Link></td>
                <td className="num">{formatRub(i.amount_kopecks)}</td>
                <td className="small">{i.provider}{i.test_mode ? <> <Badge tone="warn">тест</Badge></> : null}<div className="muted mono">{i.provider_payment_id}</div></td>
                <td><Badge tone={i.status === "needs_review" ? "danger" : "warn"}>{label(INTENT_STATUS, i.status)}</Badge>
                  {i.error ? <div className="small muted">{i.error}</div> : null}</td>
                <td className="right">{canConfirm ? <button className="btn btn-sm" onClick={() => resync(i.id)} disabled={action.busy}>Проверить статус</button> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function PaymentsPage() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const params = new URLSearchParams();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const reports = useApi<PaymentReport[]>("/api/admin/payment-reports", 10000);
  const payments = useApi<Payment[]>(`/api/admin/payments?${params}`);
  const total = (payments.data ?? []).filter((p) => p.status === "confirmed").reduce((s, p) => s + p.amount_kopecks, 0);

  return (
    <>
      <PageHead title="Рассрочки и платежи" subtitle="Подтверждение поступлений и журнал всех операций" />
      <Notice tone="info">
        Платёж считается полученным только после подтверждения сотрудником по банковским данным или кассовому документу
        (в карточке договора или в разделе <Link href="/bank">«Банковские выписки»</Link>), либо после того, как сервер сам
        проверил статус онлайн-оплаты у платёжного сервиса. Нажатие покупателем кнопки «Я оплатил» — это сообщение для
        сверки, на остаток долга оно не влияет.
      </Notice>

      <OnlineIntents />

      <Card title="Сообщения покупателей «Я оплатил»" subtitle="Ожидают сверки с банком" flush>
        <ErrorBox error={reports.error} />
        {reports.loading && !reports.data ? <Loading /> : !reports.data?.length ? <Empty>Нет сообщений на проверке</Empty> : (
          <table>
            <thead><tr><th>Получено</th><th>Договор</th><th>Покупатель</th><th className="num">Сумма</th><th>Дата оплаты (со слов)</th><th>Комментарий</th></tr></thead>
            <tbody>
              {reports.data.map((r) => (
                <tr key={r.id}>
                  <td className="small">{formatDateTime(r.created_at)}</td>
                  <td><Link href={`/contracts/${r.contract_id}`}>№ {r.contract_number}</Link></td>
                  <td>{r.client}</td>
                  <td className="num">{formatRub(r.amount_kopecks)}</td>
                  <td>{formatDate(r.paid_on)}</td>
                  <td className="small">{r.comment || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Журнал поступлений"
            subtitle={`Учтено за выбранный период: ${formatRub(total)}`}
            actions={
              <>
                <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="С" />
                <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="По" />
                <a className="btn btn-sm" href={`/api/admin/reports/payments.xlsx?${params}`}>Excel</a>
                <a className="btn btn-sm" href={`/api/admin/reports/payments.csv?${params}`}>CSV</a>
              </>
            }
            flush>
        <ErrorBox error={payments.error} />
        {payments.loading && !payments.data ? <Loading /> : !payments.data?.length ? <Empty>Поступлений нет</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Дата</th><th>Договор</th><th>Покупатель</th><th className="num">Сумма</th><th>Способ</th><th>Документ</th><th>Источник</th><th>Статус</th></tr></thead>
              <tbody>
                {payments.data.map((p) => (
                  <tr key={p.id}>
                    <td>{formatDate(p.received_on)}</td>
                    <td><Link href={`/contracts/${p.contract_id}`}>№ {p.contract_number}</Link></td>
                    <td>{p.client}</td>
                    <td className="num">{p.status === "reversed" ? <s>{formatRub(p.amount_kopecks)}</s> : formatRub(p.amount_kopecks)}</td>
                    <td className="small">{label(PAYMENT_METHOD, p.method)}</td>
                    <td className="small">{p.document_ref}</td>
                    <td className="small">{label(PAYMENT_SOURCE, p.source)}</td>
                    <td><StatusBadge status={p.status} labels={PAYMENT_STATUS} />{p.reversal_reason ? <div className="small muted">{p.reversal_reason}</div> : null}</td>
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
