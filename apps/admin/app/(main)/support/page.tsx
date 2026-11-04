"use client";

import { THREAD_STATUS, THREAD_TOPIC, type Thread, formatDateTime, label } from "@islamic-car/shared";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card, Empty, ErrorBox, Loading, PageHead, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/useApi";

export default function SupportPage() {
  const router = useRouter();
  const [status, setStatus] = useState("open");
  const { data, error, loading } = useApi<Thread[]>(`/api/admin/threads${status ? `?status=${status}` : ""}`, 10000);

  return (
    <>
      <PageHead title="Обращения клиентов" subtitle="Переписка с покупателями из личного кабинета. Запросы на изменение графика не меняют договор автоматически." />
      <div className="tabs">
        {["open", "answered", "closed", ""].map((s) => (
          <button key={s || "all"} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>{s ? THREAD_STATUS[s] : "Все"}</button>
        ))}
      </div>
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.length ? <Empty>Обращений нет</Empty> : (
          <table>
            <thead><tr><th>Тема</th><th>Клиент</th><th>Вид</th><th>Обновлено</th><th>Статус</th></tr></thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.id} className="clickable" onClick={() => router.push(`/support/${t.id}`)}>
                  <td><strong>{t.subject}</strong></td>
                  <td>{t.client?.full_name}</td>
                  <td className="small">{label(THREAD_TOPIC, t.topic)}</td>
                  <td className="small">{formatDateTime(t.updated_at)}</td>
                  <td><StatusBadge status={t.status} labels={THREAD_STATUS} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
