"use client";

import { type AppNotification, api, formatDateTime } from "@islamic-car/shared";
import { useRouter } from "next/navigation";

import { Badge, Card, Empty, ErrorBox, Loading, Notice, PageHead } from "@/components/ui";
import { useApi } from "@/lib/useApi";

export default function NotificationsPage() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<AppNotification[]>("/api/admin/notifications", 5000);

  async function open(n: AppNotification) {
    if (!n.read) await api(`/api/admin/notifications/${n.id}/read`, { method: "POST" });
    if (n.link) router.push(n.link); else reload();
  }

  return (
    <>
      <PageHead title="Центр уведомлений" subtitle="Новые заявки, сообщения об оплате, обращения клиентов"
                actions={<button className="btn btn-sm" onClick={async () => { await api("/api/admin/notifications/read-all", { method: "POST" }); reload(); }}>Отметить все прочитанными</button>} />
      <Notice tone="warn" title="Версия 1: только внутренние уведомления">
        SMS, электронная почта и мессенджеры подключаются в версии 2 через фоновый сервис уведомлений — с проверкой согласий,
        допустимого времени отправки (учёт 230-ФЗ), защитой от повторов и журналом доставки. Сейчас клиентам ничего не отправляется наружу.
      </Notice>
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.length ? <Empty>Уведомлений нет</Empty> : (
          <table>
            <tbody>
              {data.map((n) => (
                <tr key={n.id} className="clickable" onClick={() => open(n)}>
                  <td style={{ width: 170 }} className="small">{formatDateTime(n.created_at)}</td>
                  <td>{n.read ? n.title : <strong>{n.title}</strong>}{n.body ? <div className="small muted">{n.body}</div> : null}</td>
                  <td style={{ width: 110 }}>{n.read ? null : <Badge tone="warn">Новое</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
