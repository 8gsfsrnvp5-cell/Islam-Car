"use client";

import { APPLICATION_KIND, APPLICATION_STATUS, type StaffApplication, api, formatDateTime, formatRub, label } from "@islamic-car/shared";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Field, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { CLIENT_SITE_URL, useAction, useApi } from "@/lib/useApi";

const MANUAL_STATUSES = ["in_progress", "info_requested", "offer_made", "rejected"];
const FINAL = ["converted", "rejected", "withdrawn"];

export default function ApplicationPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const canWriteClients = useCan("clients.write");
  const { data: a, error, reload, setData } = useApi<StaffApplication>(`/api/admin/applications/${id}`);
  const [status, setStatus] = useState("in_progress");
  const [message, setMessage] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const action = useAction();

  if (!a) return error ? <ErrorBox error={error} /> : <Loading />;
  const statusUrl = `${CLIENT_SITE_URL}/status/${a.public_token}`;

  async function changeStatus(e: React.FormEvent) {
    e.preventDefault();
    const updated = await action.run(() => api<StaffApplication>(`/api/admin/applications/${id}/status`, {
      method: "POST", json: { status, public_message: message, internal_note: note ?? a!.internal_note },
    }));
    if (updated) { setData(updated); setMessage(""); }
  }

  async function makeClient() {
    const r = await action.run(() => api<{ client_id: string }>(`/api/admin/applications/${id}/client`, { method: "POST" }));
    if (r) { await reload(); router.push(`/clients/${r.client_id}`); }
  }

  const contractHref = `/contracts/new?client=${a.client_id ?? ""}&application=${a.id}${a.car ? `&car=${a.car.id}` : ""}`;

  return (
    <>
      <PageHead
        title={`Заявка: ${a.name}`}
        subtitle={<>{label(APPLICATION_KIND, a.kind)} · поступила {formatDateTime(a.created_at)} · <StatusBadge status={a.status} labels={APPLICATION_STATUS} /></>}
        actions={
          <>
            {a.client_id ? <Link className="btn" href={`/clients/${a.client_id}`}>Карточка клиента</Link>
              : canWriteClients ? <button className="btn" onClick={makeClient} disabled={action.busy}>Создать карточку клиента</button> : null}
            {a.client_id && a.car && !FINAL.includes(a.status) ? <Link className="btn btn-primary" href={contractHref}>Подготовить договор</Link> : null}
          </>
        }
      />
      <ErrorBox error={action.error} />
      <div className="split">
        <div>
          <Card title="Данные заявки">
            <dl className="kv">
              <dt>Имя</dt><dd>{a.name}</dd>
              <dt>Телефон</dt><dd><a href={`tel:${a.phone}`}>{a.phone}</a></dd>
              {a.car ? <><dt>Автомобиль</dt><dd>{a.car.title} <span className="muted small">{a.car.vin ?? "VIN не указан"}</span></dd></> : (
                <>
                  <dt>Нужен автомобиль</dt><dd>{a.wanted_make} {a.wanted_model}{a.wanted_year ? `, ${a.wanted_year}` : ""}</dd>
                  <dt>Комплектация</dt><dd>{a.wanted_trim || "—"}</dd>
                  <dt>Бюджет</dt><dd>{a.max_budget_kopecks ? `до ${formatRub(a.max_budget_kopecks)}` : "—"}</dd>
                </>
              )}
              <dt>Первоначальный взнос</dt><dd>{formatRub(a.desired_down_payment_kopecks)}</dd>
              <dt>Срок</dt><dd>{a.desired_term_months ? `${a.desired_term_months} мес.` : "—"}</dd>
              <dt>Комментарий</dt><dd style={{ whiteSpace: "pre-wrap" }}>{a.comment || "—"}</dd>
              <dt>Согласие на обработку ПДн</dt><dd>{a.consent_personal_data ? `получено (редакция ${a.consent_version})` : "нет"}</dd>
            </dl>
          </Card>
          {a.kind === "custom_order" ? (
            <Notice tone="info" title="Заказ автомобиля">
              Договор купли-продажи заключается только после того, как продавец купит подходящий автомобиль и оформит его в собственность.
              Добавьте автомобиль в реестр и предложите его клиенту.
            </Notice>
          ) : null}
          <Card title="История" flush>
            <table>
              <tbody>
                {a.events.map((e, i) => (
                  <tr key={i}>
                    <td className="small" style={{ width: 160 }}>{formatDateTime(e.created_at)}</td>
                    <td><StatusBadge status={e.to_status} labels={APPLICATION_STATUS} /></td>
                    <td className="small">{e.public_message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
        <div>
          <Card title="Статус для клиента" subtitle="Клиент видит статус и сообщение по своей ссылке">
            <p className="small">Ссылка на статус (отправьте клиенту по подтверждённому номеру):</p>
            <div className="secret small mono">{statusUrl}</div>
            <p className="small muted" style={{ marginTop: 8 }}>Сообщение сейчас: «{a.public_message}»</p>
          </Card>
          {!FINAL.includes(a.status) ? (
            <Card title="Изменить статус">
              <form onSubmit={changeStatus} className="grid">
                <Field label="Новый статус">
                  <select value={status} onChange={(e) => setStatus(e.target.value)}>
                    {MANUAL_STATUSES.map((s) => <option key={s} value={s}>{APPLICATION_STATUS[s]}</option>)}
                  </select>
                </Field>
                <Field label="Сообщение клиенту" hint={status === "rejected" ? "Обязательно при отказе. Корректно и без дискриминирующих формулировок." : "Будет видно на странице статуса"}>
                  <textarea value={message} onChange={(e) => setMessage(e.target.value)} required={status === "rejected"} />
                </Field>
                <Field label="Внутренняя заметка" hint="Клиент её не видит">
                  <textarea value={note ?? a.internal_note} onChange={(e) => setNote(e.target.value)} />
                </Field>
                <button className="btn btn-primary" disabled={action.busy}>Сохранить</button>
              </form>
            </Card>
          ) : <Notice>Заявка закрыта: {APPLICATION_STATUS[a.status]}</Notice>}
        </div>
      </div>
    </>
  );
}
