"use client";

import {
  CHANNEL, MESSAGE_STATUS, NOTIFY_EVENT, type AppNotification, type OutMessage, api, formatDateTime,
} from "@islamic-car/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Field, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Rule = { id: string | null; event: string; offset_days: number; channels: string[]; enabled: boolean };
type Policy = Record<string, string | number | string[]>;
type ChannelState = { channel: string; connected: boolean; provider: string; test_mode: boolean; note?: string };
type Settings = { rules: Rule[]; policy: Policy; channels: ChannelState[] };
type Worker = { alive: boolean; last_seen: string | null; jobs: Record<string, number>; failed: { id: string; kind: string; attempts: number; error: string; finished_at: string }[] };

function StaffTab() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<AppNotification[]>("/api/admin/notifications", 5000);
  async function open(n: AppNotification) {
    if (!n.read) await api(`/api/admin/notifications/${n.id}/read`, { method: "POST" });
    if (n.link) router.push(n.link); else reload();
  }
  return (
    <>
      <div className="actions" style={{ marginBottom: 10 }}>
        <button className="btn btn-sm" onClick={async () => { await api("/api/admin/notifications/read-all", { method: "POST" }); reload(); }}>Отметить все прочитанными</button>
      </div>
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.length ? <Empty>Уведомлений нет</Empty> : (
          <table><tbody>
            {data.map((n) => (
              <tr key={n.id} className="clickable" onClick={() => open(n)}>
                <td style={{ width: 170 }} className="small">{formatDateTime(n.created_at)}</td>
                <td>{n.read ? n.title : <strong>{n.title}</strong>}{n.body ? <div className="small muted">{n.body}</div> : null}</td>
                <td style={{ width: 110 }}>{n.read ? null : <Badge tone="warn">Новое</Badge>}</td>
              </tr>
            ))}
          </tbody></table>
        )}
      </Card>
    </>
  );
}

function JournalTab() {
  const [status, setStatus] = useState("");
  const { data, error, loading } = useApi<{ items: OutMessage[]; counts: Record<string, number> }>(`/api/admin/messages${status ? `?status=${status}` : ""}`, 15000);
  return (
    <>
      <div className="tabs">
        {["", "scheduled", "sent", "skipped", "cancelled", "failed"].map((s) => (
          <button key={s || "all"} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>
            {s ? MESSAGE_STATUS[s] : "Все"}{s && data?.counts[s] ? ` · ${data.counts[s]}` : ""}
          </button>
        ))}
      </div>
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.items.length ? <Empty>Сообщений пока нет. Их создаёт фоновый обработчик по правилам ниже.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Создано</th><th>Клиент / договор</th><th>Канал</th><th>Текст</th><th>Статус</th></tr></thead>
              <tbody>
                {data.items.map((m) => (
                  <tr key={m.id}>
                    <td className="small">{formatDateTime(m.created_at)}<div className="muted">{NOTIFY_EVENT[m.purpose]}</div></td>
                    <td className="small">{m.client}{m.contract_id ? <div><Link href={`/contracts/${m.contract_id}`}>№ {m.contract_number}</Link></div> : null}</td>
                    <td className="small">{CHANNEL[m.channel]}{m.address_masked ? <div className="muted mono">{m.address_masked}</div> : null}</td>
                    <td className="small" style={{ maxWidth: 380 }}>{m.body}</td>
                    <td><StatusBadge status={m.status} labels={MESSAGE_STATUS} />
                      <div className="small muted">{m.status === "sent" ? formatDateTime(m.sent_at) : m.status === "scheduled" ? `на ${formatDateTime(m.scheduled_for)}` : ""}</div>
                      {m.status_reason ? <div className="small muted">{m.status_reason}</div> : null}</td>
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

function RulesTab() {
  const canWrite = useCan("settings.write");
  const { data, error, setData } = useApi<Settings>("/api/admin/notification-settings");
  const [rules, setRules] = useState<Rule[]>([]);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const action = useAction();
  useEffect(() => { if (data) { setRules(data.rules); setPolicy(data.policy); } }, [data]);
  if (!data || !policy) return error ? <ErrorBox error={error} /> : <Loading />;

  const update = (i: number, patch: Partial<Rule>) => setRules(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  async function saveRules() {
    const r = await action.run(() => api<Settings>("/api/admin/notification-settings/rules", { method: "PUT", json: { rules } }));
    if (r) { setData(r); setSaved("Правила сохранены"); }
  }
  async function savePolicy() {
    const { basis: _b, ...payload } = policy!;
    const r = await action.run(() => api<Settings>("/api/admin/notification-settings/policy", { method: "PUT", json: payload }));
    if (r) { setData(r); setSaved("Правила времени и частоты сохранены"); }
  }

  return (
    <>
      <ErrorBox error={action.error} />
      {saved ? <Notice tone="ok">{saved}</Notice> : null}
      <Card title="Каналы">
        <div className="actions">
          {data.channels.map((c) => (
            <span key={c.channel} className="chip"><span className={`dot ${c.connected ? "ok" : "bad"}`} />{CHANNEL[c.channel]}:
              {c.connected ? (c.test_mode ? " тестовый режим — наружу не отправляется" : ` подключён (${c.provider})`) : " не подключён"}
              {c.note ? <span className="muted"> · {c.note}</span> : null}</span>
          ))}
        </div>
        <p className="small muted" style={{ marginTop: 8 }}>
          SMS отправляются через SMS.ru после договора с оператором и согласования имени отправителя (ключ — в настройках сервера, не в GitHub).
          E-mail — через SMTP. Сообщения уходят только на подтверждённые контакты при наличии согласия клиента на канал.
        </p>
      </Card>
      <Card title="Расписание напоминаний" subtitle="Все интервалы настраиваются. Перед отправкой долг проверяется заново — оплаченный платёж не вызывает напоминания">
        <table>
          <thead><tr><th>Событие</th><th>Дней</th><th>Каналы</th><th>Включено</th></tr></thead>
          <tbody>
            {rules.map((r, i) => (
              <tr key={r.id ?? i}>
                <td><select value={r.event} onChange={(e) => update(i, { event: e.target.value })} disabled={!canWrite}>
                  {Object.entries(NOTIFY_EVENT).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></td>
                <td style={{ width: 90 }}>{["before_due", "overdue"].includes(r.event)
                  ? <input type="number" min={0} max={60} value={r.offset_days} onChange={(e) => update(i, { offset_days: Number(e.target.value) })} disabled={!canWrite} />
                  : <span className="muted">—</span>}</td>
                <td><div className="actions">{["internal", "sms", "email"].map((ch) => (
                  <label key={ch} className="check small"><input type="checkbox" checked={r.channels.includes(ch)} disabled={!canWrite}
                    onChange={(e) => update(i, { channels: e.target.checked ? [...r.channels, ch] : r.channels.filter((x) => x !== ch) })} />{CHANNEL[ch]}</label>
                ))}</div></td>
                <td><input type="checkbox" checked={r.enabled} onChange={(e) => update(i, { enabled: e.target.checked })} disabled={!canWrite} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {canWrite ? (
          <div className="actions" style={{ marginTop: 10 }}>
            <button className="btn btn-sm" onClick={() => setRules([...rules, { id: null, event: "before_due", offset_days: 3, channels: ["internal"], enabled: true }])}>Добавить правило</button>
            <button className="btn btn-primary btn-sm" onClick={saveRules} disabled={action.busy}>Сохранить правила</button>
          </div>
        ) : null}
      </Card>
      <Card title="Время и частота сообщений" subtitle={String(policy.basis ?? "")}>
        <div className="form-grid">
          <Field label="Будни: с"><input value={String(policy.weekday_from)} onChange={(e) => setPolicy({ ...policy, weekday_from: e.target.value })} disabled={!canWrite} /></Field>
          <Field label="Будни: до"><input value={String(policy.weekday_to)} onChange={(e) => setPolicy({ ...policy, weekday_to: e.target.value })} disabled={!canWrite} /></Field>
          <Field label="Выходные и праздники: с"><input value={String(policy.weekend_from)} onChange={(e) => setPolicy({ ...policy, weekend_from: e.target.value })} disabled={!canWrite} /></Field>
          <Field label="Выходные и праздники: до"><input value={String(policy.weekend_to)} onChange={(e) => setPolicy({ ...policy, weekend_to: e.target.value })} disabled={!canWrite} /></Field>
          <Field label="Сообщений о просрочке в сутки, не более"><input type="number" value={Number(policy.overdue_per_day)} onChange={(e) => setPolicy({ ...policy, overdue_per_day: Number(e.target.value) })} disabled={!canWrite} /></Field>
          <Field label="В неделю, не более"><input type="number" value={Number(policy.overdue_per_week)} onChange={(e) => setPolicy({ ...policy, overdue_per_week: Number(e.target.value) })} disabled={!canWrite} /></Field>
          <Field label="В месяц, не более"><input type="number" value={Number(policy.overdue_per_month)} onChange={(e) => setPolicy({ ...policy, overdue_per_month: Number(e.target.value) })} disabled={!canWrite} /></Field>
          <Field label="Праздничные дни (ГГГГ-ММ-ДД через запятую)" hint="Производственный календарь на год вносится вручную">
            <input value={(policy.holidays as string[]).join(", ")} disabled={!canWrite}
                   onChange={(e) => setPolicy({ ...policy, holidays: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
          </Field>
        </div>
        <p className="small muted" style={{ marginTop: 8 }}>Время считается по часовому поясу клиента. Ограничения частоты применяются к сообщениям о просрочке гражданам и ИП.</p>
        {canWrite ? <button className="btn btn-primary btn-sm" onClick={savePolicy} disabled={action.busy}>Сохранить</button> : null}
      </Card>
    </>
  );
}

function WorkerTab() {
  const { data, error } = useApi<Worker>("/api/admin/worker", 10000);
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  return (
    <>
      {data.alive ? <Notice tone="ok" title="Фоновый обработчик работает">Последний сигнал: {formatDateTime(data.last_seen)}</Notice>
        : <Notice tone="danger" title="Фоновый обработчик не отвечает">Напоминания и контроль сроков не выполняются. Запустите сервис worker (см. docs/run-windows.md). Последний сигнал: {formatDateTime(data.last_seen)}</Notice>}
      <Card title="Очередь задач">
        <div className="actions">{Object.entries(data.jobs).map(([k, v]) => <span key={k} className="chip">{k}: {v}</span>)}</div>
      </Card>
      {data.failed.length ? (
        <Card title="Задачи с ошибками" flush>
          <table><tbody>{data.failed.map((f) => (
            <tr key={f.id}><td className="small">{formatDateTime(f.finished_at)}</td><td className="mono small">{f.kind}</td><td className="small muted" style={{ whiteSpace: "pre-wrap" }}>{f.error}</td></tr>
          ))}</tbody></table>
        </Card>
      ) : null}
    </>
  );
}

const TABS = { staff: "Сотрудникам", journal: "Журнал сообщений клиентам", rules: "Правила отправки", worker: "Фоновый обработчик" } as const;

export default function NotificationsPage() {
  const [tab, setTab] = useState<keyof typeof TABS>("staff");
  return (
    <>
      <PageHead title="Центр уведомлений" subtitle="Внутренние уведомления, напоминания клиентам и журнал всех сообщений" />
      <div className="tabs">
        {(Object.keys(TABS) as (keyof typeof TABS)[]).map((k) => <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{TABS[k]}</button>)}
      </div>
      {tab === "staff" ? <StaffTab /> : tab === "journal" ? <JournalTab /> : tab === "rules" ? <RulesTab /> : <WorkerTab />}
    </>
  );
}
