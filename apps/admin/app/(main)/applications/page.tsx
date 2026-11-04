"use client";

import { APPLICATION_KIND, APPLICATION_STATUS, type StaffApplication, formatDateTime, formatRub, label } from "@islamic-car/shared";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card, Empty, ErrorBox, Loading, PageHead, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/useApi";

const FILTERS = ["", "new", "in_progress", "info_requested", "offer_made", "converted", "rejected", "withdrawn"];

export default function ApplicationsPage() {
  const router = useRouter();
  const [status, setStatus] = useState("");
  // Обновление каждые 5 секунд: новая заявка с сайта появляется без перезагрузки страницы
  const { data, error, loading } = useApi<StaffApplication[]>(`/api/admin/applications${status ? `?status=${status}` : ""}`, 5000);

  return (
    <>
      <PageHead title="Заявки клиентов" subtitle="Заявки с сайта на автомобили из каталога и заказы автомобилей, которых нет в каталоге" />
      <div className="tabs">
        {FILTERS.map((s) => (
          <button key={s || "all"} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>
            {s ? APPLICATION_STATUS[s] : "Все"}
          </button>
        ))}
      </div>
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.length ? <Empty>Заявок нет</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Поступила</th><th>Клиент</th><th>Автомобиль / запрос</th><th className="num">Взнос</th><th className="num">Срок</th><th>Тип</th><th>Статус</th></tr>
              </thead>
              <tbody>
                {data.map((a) => (
                  <tr key={a.id} className="clickable" onClick={() => router.push(`/applications/${a.id}`)}>
                    <td className="small">{formatDateTime(a.created_at)}</td>
                    <td><strong>{a.name}</strong><div className="small muted">{a.phone}</div></td>
                    <td>{a.car ? a.car.title : `${a.wanted_make} ${a.wanted_model}${a.wanted_year ? `, ${a.wanted_year}` : ""}`}
                      {a.max_budget_kopecks ? <div className="small muted">бюджет до {formatRub(a.max_budget_kopecks)}</div> : null}
                    </td>
                    <td className="num">{formatRub(a.desired_down_payment_kopecks)}</td>
                    <td className="num">{a.desired_term_months ? `${a.desired_term_months} мес.` : "—"}</td>
                    <td>{label(APPLICATION_KIND, a.kind)}</td>
                    <td><StatusBadge status={a.status} labels={APPLICATION_STATUS} /></td>
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
