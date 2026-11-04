"use client";

import {
  APPLICATION_STATUS, CONTRACT_STATUS, PARTY_TYPE, THREAD_STATUS, THREAD_TOPIC, type StaffApplication, type StaffContract, type Thread,
  api, formatDate, formatDateTime, formatRub, label,
} from "@islamic-car/shared";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { type ClientData, ClientForm } from "@/components/ClientForm";
import { ConfirmButton } from "@/components/Confirm";
import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { CLIENT_SITE_URL, useAction, useApi } from "@/lib/useApi";

type ClientFull = ClientData & { contracts: StaffContract[]; applications: StaffApplication[]; threads: Thread[] };

export default function ClientPage() {
  const { id } = useParams<{ id: string }>();
  const canWrite = useCan("clients.write");
  const canVerify = useCan("clients.verify");
  const canAccess = useCan("clients.access");
  const { data: c, error, reload } = useApi<ClientFull>(`/api/admin/clients/${id}`);
  const action = useAction();
  const [editing, setEditing] = useState(false);
  const [access, setAccess] = useState<{ activation_path: string; login: string; expires_in_hours: number } | null>(null);

  if (!c) return error ? <ErrorBox error={error} /> : <Loading />;

  async function save(payload: Record<string, unknown>) {
    const r = await action.run(() => api(`/api/admin/clients/${id}`, { method: "PATCH", json: payload }));
    if (r) { setEditing(false); reload(); }
  }
  async function verify() {
    if (await action.run(() => api(`/api/admin/clients/${id}/verify`, { method: "POST" }))) reload();
  }
  async function issueAccess() {
    const r = await action.run(() => api<typeof access>(`/api/admin/clients/${id}/access`, { method: "POST" }));
    if (r) { setAccess(r); reload(); }
  }

  const activationUrl = access ? `${CLIENT_SITE_URL}${access.activation_path}` : "";

  return (
    <>
      <PageHead
        title={c.full_name}
        subtitle={<>{label(PARTY_TYPE, c.party_type)} · в реестре с {formatDate(c.created_at)} · {c.identity_verified
          ? <Badge tone="ok">Личность проверена {formatDate(c.identity_verified_at)}</Badge> : <Badge tone="warn">Личность не проверена</Badge>}</>}
        actions={
          <>
            {canWrite && !editing ? <button className="btn" onClick={() => setEditing(true)}>Редактировать</button> : null}
            {canVerify && !c.identity_verified ? (
              <ConfirmButton label="Подтвердить личность" question="Личность проверена по оригиналу документа?"
                             confirmLabel="Да, проверена" onConfirm={verify} disabled={action.busy} />
            ) : null}
            {canAccess && c.identity_verified ? (
              <button className="btn" onClick={issueAccess} disabled={action.busy}>{c.has_cabinet_access ? "Выдать новую ссылку для входа" : "Выдать доступ в кабинет"}</button>
            ) : null}
            <Link className="btn btn-primary" href={`/contracts/new?client=${c.id}`}>Подготовить договор</Link>
          </>
        }
      />
      <ErrorBox error={action.error} />
      {access ? (
        <Notice tone="ok" title="Ссылка для установки пароля создана">
          <p className="small">Передайте её клиенту лично или на подтверждённый номер. Ссылка одноразовая и действует {access.expires_in_hours} ч. Логин: <strong>{access.login}</strong></p>
          <div className="secret mono small">{activationUrl}</div>
          <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => navigator.clipboard.writeText(activationUrl)}>Скопировать</button>
        </Notice>
      ) : null}

      <div className="split">
        <div>
          <Card title="Данные клиента">
            {editing ? <ClientForm client={c} busy={action.busy} onSubmit={save} submitLabel="Сохранить" /> : (
              <dl className="kv">
                <dt>Телефон</dt><dd>{c.phone}</dd>
                <dt>E-mail</dt><dd>{c.email || "—"}</dd>
                <dt>Адрес</dt><dd>{c.address || "—"}</dd>
                {c.party_type === "individual" ? (
                  <>
                    <dt>Дата рождения</dt><dd>{formatDate(c.birth_date)}</dd>
                    <dt>Паспорт</dt><dd>{c.passport_number || "—"} {c.passport_issued_by ? `, выдан ${c.passport_issued_by} ${formatDate(c.passport_issue_date)}` : ""}</dd>
                  </>
                ) : (
                  <>
                    <dt>ИНН / ОГРН</dt><dd>{c.inn || "—"} / {c.ogrn || "—"}</dd>
                    {c.party_type === "llc" ? <><dt>КПП</dt><dd>{c.kpp || "—"}</dd><dt>Представитель</dt><dd>{c.representative || "—"}</dd></> : null}
                  </>
                )}
                <dt>Часовой пояс</dt><dd>{c.timezone}</dd>
                <dt>Личный кабинет</dt><dd>{c.has_cabinet_access ? `активен, логин ${c.cabinet_login}` : c.cabinet_login ? "ссылка выдана, пароль не установлен" : "нет"}</dd>
                <dt>Заметки</dt><dd style={{ whiteSpace: "pre-wrap" }}>{c.notes || "—"}</dd>
              </dl>
            )}
            {c.pd_masked ? <p className="small muted">Часть персональных данных скрыта по правам доступа.</p> : null}
          </Card>
          <Card title="Договоры" flush>
            {!c.contracts.length ? <Empty>Договоров нет</Empty> : (
              <table>
                <thead><tr><th>Договор</th><th>Автомобиль</th><th className="num">Цена</th><th className="num">Остаток</th><th>Статус</th></tr></thead>
                <tbody>
                  {c.contracts.map((k) => (
                    <tr key={k.id}>
                      <td><Link href={`/contracts/${k.id}`}>{k.number ? `№ ${k.number}` : "Черновик"}</Link></td>
                      <td>{k.car.title}</td>
                      <td className="num">{formatRub(k.sale_price_kopecks)}</td>
                      <td className="num">{k.ledger ? formatRub(k.ledger.outstanding_kopecks) : "—"}{k.ledger?.overdue_kopecks ? <div><Badge tone="danger">просрочка {formatRub(k.ledger.overdue_kopecks)}</Badge></div> : null}</td>
                      <td><StatusBadge status={k.status} labels={CONTRACT_STATUS} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
        <div>
          <Card title="Заявки" flush>
            {!c.applications.length ? <Empty>Нет связанных заявок</Empty> : (
              <table><tbody>
                {c.applications.map((a) => (
                  <tr key={a.id}><td><Link href={`/applications/${a.id}`}>{a.car?.title ?? `${a.wanted_make} ${a.wanted_model}`}</Link>
                    <div className="small muted">{formatDateTime(a.created_at)}</div></td>
                  <td><StatusBadge status={a.status} labels={APPLICATION_STATUS} /></td></tr>
                ))}
              </tbody></table>
            )}
          </Card>
          <Card title="Обращения" flush>
            {!c.threads.length ? <Empty>Обращений нет</Empty> : (
              <table><tbody>
                {c.threads.map((t) => (
                  <tr key={t.id}><td><Link href={`/support/${t.id}`}>{t.subject}</Link><div className="small muted">{label(THREAD_TOPIC, t.topic)}</div></td>
                  <td><StatusBadge status={t.status} labels={THREAD_STATUS} /></td></tr>
                ))}
              </tbody></table>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
