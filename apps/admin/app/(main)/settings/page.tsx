"use client";

import { ROLE, SELLER_REGIME, api, formatDateTime, label } from "@islamic-car/shared";
import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { ConfirmButton } from "@/components/Confirm";
import { useCan, useMe } from "@/components/Shell";
import { Badge, Card, ErrorBox, Field, Loading, Notice, PageHead } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Company = Record<string, string | number>;
type StaffUser = { id: string; login: string; full_name: string; role: string; is_active: boolean; totp_enabled: boolean; last_login_at: string | null };
type AuditRow = { id: string; action: string; entity_type: string; entity_id: string | null; actor: string; actor_role: string | null; ip: string | null; created_at: string; data: unknown };

const COMPANY_FIELDS: [string, string, string?][] = [
  ["seller_name", "Продавец: ФИО ИП или наименование ООО"],
  ["seller_inn", "ИНН продавца"],
  ["seller_ogrn", "ОГРН / ОГРНИП"],
  ["seller_address", "Адрес продавца"],
  ["support_phone", "Телефон для клиентов"],
  ["bank_payee", "Получатель платежа", "Показывается покупателям в личном кабинете"],
  ["bank_name", "Банк"],
  ["bank_bik", "БИК"],
  ["bank_account", "Расчётный счёт"],
  ["bank_corr_account", "Корреспондентский счёт"],
  ["payment_purpose_hint", "Назначение платежа", "{number} заменяется номером договора"],
  ["contract_prefix", "Префикс номера договора", "Например IC → IC-2026-0001"],
];

const STAFF_ROLES = ["admin", "manager", "accountant", "lawyer", "shariah_advisor", "auditor"];
const ROLE_HINT: Record<string, string> = {
  admin: "Все операции, кроме управления пользователями и утверждения налоговых правил",
  manager: "Заявки, клиенты, автомобили, договоры, обращения",
  accountant: "Платежи, выписки, бухгалтерия, отчёты; заключения по бухгалтерской библиотеке",
  lawyer: "Документы, утверждение шаблонов, заключения по юридической библиотеке, проверка документов",
  shariah_advisor: "Проверка принципов мурабахи, заключения по библиотеке исламского финансирования",
  auditor: "Только просмотр: финансы, отчёты, журнал действий. Паспортные данные и контакты скрыты",
};

type Assistant = { enabled: boolean; configured: boolean; model: string; reason: string; changed_at: string | null; data_scope: string };

function AssistantCard() {
  const { data, error, setData } = useApi<Assistant>("/api/admin/assistant");
  const [confirm, setConfirm] = useState(false);
  const action = useAction();
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const save = async (enabled: boolean) => {
    const r = await action.run(() => api<Assistant>("/api/admin/assistant/settings",
      { method: "PUT", json: { enabled, confirm_data_scope: confirm } }));
    if (r) { setData(r); setConfirm(false); }
  };
  return (
    <Card title="Помощник по нормам (Claude API)" subtitle="По умолчанию выключен. Включает владелец">
      <p className="small">{data.data_scope}</p>
      <p className="small">Состояние: {data.enabled ? <Badge tone="ok">включён · {data.model}</Badge> : <Badge>выключен</Badge>}
        {data.reason ? <span className="muted"> — {data.reason}</span> : null}
        {data.changed_at ? <span className="muted"> · изменено {formatDateTime(data.changed_at)}</span> : null}</p>
      <ErrorBox error={action.error} />
      {data.enabled ? (
        <button className="btn btn-sm" onClick={() => save(false)} disabled={action.busy}>Выключить</button>
      ) : data.configured ? (
        <div className="actions">
          <label className="small"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />{" "}
            Подтверждаю состав передаваемых данных</label>
          <button className="btn btn-sm btn-primary" onClick={() => save(true)} disabled={action.busy || !confirm}>Включить</button>
        </div>
      ) : <Notice tone="info">Чтобы включить помощника, администратор сервера задаёт ANTHROPIC_API_KEY в переменных окружения.</Notice>}
    </Card>
  );
}

type RecognitionSettings = { enabled: boolean; configured: boolean; model: string; reason: string; changed_at: string | null; data_scope: string };

function RecognitionCard() {
  const { data, error, setData } = useApi<RecognitionSettings>("/api/admin/cars/recognition");
  const [confirm, setConfirm] = useState(false);
  const action = useAction();
  if (!data) return error ? <ErrorBox error={error} /> : null;
  const save = async (enabled: boolean) => {
    const r = await action.run(() => api<RecognitionSettings>("/api/admin/cars/recognition/settings",
      { method: "PUT", json: { enabled, confirm_data_scope: confirm } }));
    if (r) { setData(r); setConfirm(false); }
  };
  return (
    <Card title="Распознавание автомобиля по фото (Claude API)" subtitle="Подставляет марку, модель, кузов и цвет в карточку. По умолчанию выключено">
      <p className="small">{data.data_scope}</p>
      <p className="small">Состояние: {data.enabled ? <Badge tone="ok">включено · {data.model}</Badge> : <Badge>выключено</Badge>}
        {data.reason ? <span className="muted"> — {data.reason}</span> : null}
        {data.changed_at ? <span className="muted"> · изменено {formatDateTime(data.changed_at)}</span> : null}</p>
      <ErrorBox error={action.error} />
      {data.enabled ? (
        <button className="btn btn-sm" onClick={() => save(false)} disabled={action.busy}>Выключить</button>
      ) : data.configured ? (
        <div className="actions">
          <label className="small"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />{" "}
            Подтверждаю состав передаваемых данных</label>
          <button className="btn btn-sm btn-primary" onClick={() => save(true)} disabled={action.busy || !confirm}>Включить</button>
        </div>
      ) : <Notice tone="info">Чтобы включить распознавание, администратор сервера задаёт ANTHROPIC_API_KEY в переменных окружения. Каждое распознавание — платный запрос к Claude API.</Notice>}
    </Card>
  );
}

function CompanyCard() {
  const canWrite = useCan("settings.write");
  const { data, error, setData } = useApi<Company>("/api/admin/settings");
  const [form, setForm] = useState<Company | null>(null);
  const action = useAction();
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (data && !form) setForm(data); }, [data, form]);
  if (!form) return error ? <ErrorBox error={error} /> : <Loading />;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const { next_contract_seq: _seq, ...payload } = form!;
    const r = await action.run(() => api<Company>("/api/admin/settings", { method: "PUT", json: payload }));
    if (r) { setData(r); setForm(r); setSaved(true); }
  }

  return (
    <Card title="Продавец и реквизиты для оплаты" subtitle="Хранятся в базе, а не в коде и не в GitHub">
      <form onSubmit={save}>
        <div className="form-grid">
          <Field label="Правовой режим продавца" wide hint="Разовая продажа личного имущества не может маскировать регулярную предпринимательскую деятельность">
            <select value={String(form.seller_regime)} onChange={(e) => setForm({ ...form, seller_regime: e.target.value })} disabled={!canWrite}>
              {Object.entries(SELLER_REGIME).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>
          </Field>
          {COMPANY_FIELDS.map(([key, title, hint]) => (
            <Field key={key} label={title} hint={hint}>
              <input value={String(form[key] ?? "")} onChange={(e) => setForm({ ...form, [key]: e.target.value })} disabled={!canWrite} />
            </Field>
          ))}
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>Следующий номер договора: {String(form.next_contract_seq)}</p>
        <ErrorBox error={action.error} />
        {saved ? <div className="form-ok">Сохранено</div> : null}
        {canWrite ? <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={action.busy}>Сохранить</button>
          : <p className="small muted">Изменять настройки может только владелец.</p>}
      </form>
    </Card>
  );
}

function AccountCard() {
  const me = useMe();
  const [pw, setPw] = useState({ current: "", next: "" });
  const [totp, setTotp] = useState<{ secret: string; uri: string; qr: string } | null>(null);
  const [code, setCode] = useState("");
  const [enabled, setEnabled] = useState(me.totp_enabled);
  const [msg, setMsg] = useState<string | null>(null);
  const action = useAction();

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    if (await action.run(() => api("/api/auth/admin/password", { method: "POST", json: { current_password: pw.current, new_password: pw.next } }))) {
      setPw({ current: "", next: "" }); setMsg("Пароль изменён");
    }
  }
  async function startTotp() {
    const r = await action.run(() => api<{ secret: string; otpauth_uri: string }>("/api/auth/admin/totp/setup", { method: "POST" }));
    if (r) setTotp({ secret: r.secret, uri: r.otpauth_uri, qr: await QRCode.toDataURL(r.otpauth_uri, { margin: 1, width: 180 }) });
  }
  async function enableTotp(e: React.FormEvent) {
    e.preventDefault();
    if (await action.run(() => api("/api/auth/admin/totp/enable", { method: "POST", json: { code } }))) {
      setEnabled(true); setTotp(null); setCode(""); setMsg("Второй фактор включён. При следующем входе потребуется код.");
    }
  }

  return (
    <Card title="Моя учётная запись" subtitle={`${me.full_name} · ${label(ROLE, me.role)} · ${me.login}`}>
      {msg ? <Notice tone="ok">{msg}</Notice> : null}
      <ErrorBox error={action.error} />
      <h3>Второй фактор входа</h3>
      {enabled ? <p><Badge tone="ok">Включён</Badge></p> : (
        <>
          {me.role === "owner" ? <Notice tone="warn">Для владельца второй фактор обязателен перед работой с реальными данными.</Notice> : null}
          {!totp ? <button className="btn" onClick={startTotp} disabled={action.busy}>Настроить приложение-аутентификатор</button> : (
            <form onSubmit={enableTotp} className="grid">
              <p className="small">Отсканируйте код в приложении-аутентификаторе или введите ключ вручную, затем введите 6 цифр.</p>
              <img src={totp.qr} alt="QR-код для приложения-аутентификатора" width={180} height={180} />
              <div className="secret mono small">{totp.secret}</div>
              <Field label="Код из приложения"><input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" required /></Field>
              <button className="btn btn-primary" disabled={action.busy}>Включить</button>
            </form>
          )}
        </>
      )}
      <h3 style={{ marginTop: 18 }}>Смена пароля</h3>
      <form onSubmit={changePassword} className="grid">
        <Field label="Текущий пароль"><input type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" required /></Field>
        <Field label="Новый пароль" hint="Не короче 10 символов"><input type="password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" required /></Field>
        <div><button className="btn" disabled={action.busy}>Изменить пароль</button></div>
      </form>
    </Card>
  );
}

function UsersCard() {
  const { data, error, reload } = useApi<StaffUser[]>("/api/admin/users");
  const [form, setForm] = useState({ login: "", full_name: "", role: "manager", password: "" });
  const action = useAction();

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (await action.run(() => api("/api/admin/users", { method: "POST", json: form }))) {
      setForm({ login: "", full_name: "", role: "manager", password: "" }); reload();
    }
  }
  async function deactivate(u: StaffUser) {
    if (await action.run(() => api(`/api/admin/users/${u.id}/deactivate`, { method: "POST" }))) reload();
  }

  return (
    <Card title="Сотрудники" subtitle="Права проверяются на сервере для каждого действия">
      <ErrorBox error={error ?? action.error} />
      <table>
        <thead><tr><th>Сотрудник</th><th>Роль</th><th>2FA</th><th>Последний вход</th><th></th></tr></thead>
        <tbody>
          {data?.map((u) => (
            <tr key={u.id}>
              <td>{u.full_name}<div className="small muted">{u.login}</div></td>
              <td>{label(ROLE, u.role)}</td>
              <td>{u.totp_enabled ? <Badge tone="ok">Да</Badge> : <Badge>Нет</Badge>}</td>
              <td className="small">{formatDateTime(u.last_login_at)}</td>
              <td className="right">{u.is_active ? (
                <ConfirmButton label="Отключить" question="Отключить доступ?" onConfirm={() => deactivate(u)} danger small />
              ) : <Badge>Отключён</Badge>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form onSubmit={create} className="form-grid" style={{ marginTop: 16 }}>
        <Field label="Логин (e-mail)"><input value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} required /></Field>
        <Field label="ФИО"><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required /></Field>
        <Field label="Роль">
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {STAFF_ROLES.map((r) => <option key={r} value={r}>{ROLE[r]}</option>)}
          </select>
          <small>{ROLE_HINT[form.role]}</small>
        </Field>
        <Field label="Начальный пароль" hint="Сотрудник сменит его после входа"><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" required /></Field>
        <div className="wide"><button className="btn btn-primary" disabled={action.busy}>Добавить сотрудника</button></div>
      </form>
    </Card>
  );
}

function AuditCard() {
  const { data, error } = useApi<AuditRow[]>("/api/admin/audit?limit=100");
  return (
    <Card title="Журнал действий" subtitle="Последние 100 записей. Записи только добавляются." flush>
      <ErrorBox error={error} />
      <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
        <table>
          <thead><tr><th>Время</th><th>Кто</th><th>Действие</th><th>Объект</th><th>IP</th></tr></thead>
          <tbody>
            {data?.map((a) => (
              <tr key={a.id}>
                <td className="small">{formatDateTime(a.created_at)}</td>
                <td className="small">{a.actor}{a.actor_role ? ` (${label(ROLE, a.actor_role)})` : ""}</td>
                <td className="mono small">{a.action}</td>
                <td className="small">{a.entity_type} <span className="muted mono">{a.entity_id?.slice(0, 8)}</span></td>
                <td className="small muted">{a.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

type Backups = {
  configured: boolean; retention_days: number; backup_hour: number; full_restore_check: boolean;
  runs: { id: string; kind: string; status: string; file_name: string; size_bytes: number; detail: string; started_at: string }[];
};

function BackupsCard() {
  const { data, error, reload } = useApi<Backups>("/api/admin/backups", 15000);
  const action = useAction();
  const [msg, setMsg] = useState<string | null>(null);
  const run = async (kind: string) => {
    const r = await action.run(() => api<{ message: string }>(`/api/admin/backups/${kind}`, { method: "POST" }));
    if (r) { setMsg(r.message); reload(); }
  };
  if (!data) return error ? <ErrorBox error={error} /> : null;
  return (
    <Card title="Резервные копии" subtitle="Выполняет фоновый обработчик: база (pg_dump) и файлы, проверка восстановления">
      <ErrorBox error={action.error} />
      {msg ? <Notice tone="ok">{msg}</Notice> : null}
      {data.configured ? (
        <p className="small">Ежедневно в {data.backup_hour}:00, хранение {data.retention_days} дн. Проверка восстановления — еженедельно,
          {data.full_restore_check ? " полным восстановлением в отдельную базу." : " по целостности архива (полное восстановление не настроено)."}</p>
      ) : <Notice tone="warn" title="Не настроено">Задайте BACKUP_DIR на сервере (каталог вне веб-доступа, лучше на отдельном диске). Работает только с PostgreSQL.</Notice>}
      <div className="actions" style={{ marginBottom: 10 }}>
        <button className="btn btn-sm" onClick={() => run("backup")} disabled={action.busy}>Сделать копию сейчас</button>
        <button className="btn btn-sm" onClick={() => run("verify_backup")} disabled={action.busy}>Проверить последнюю</button>
      </div>
      <table><tbody>
        {data.runs.map((r) => (
          <tr key={r.id}>
            <td className="small">{formatDateTime(r.started_at)}</td>
            <td className="small">{r.kind === "backup" ? "Копия" : "Проверка"}</td>
            <td>{r.status === "ok" ? <Badge tone="ok">успешно</Badge> : r.status === "failed" ? <Badge tone="danger">ошибка</Badge> : <Badge>{r.status}</Badge>}</td>
            <td className="small muted">{r.file_name} {r.size_bytes ? `· ${(r.size_bytes / 1024 / 1024).toFixed(1)} МБ` : ""}<div>{r.detail}</div></td>
          </tr>
        ))}
      </tbody></table>
    </Card>
  );
}

export default function SettingsPage() {
  const canUsers = useCan("users.manage");
  const canAudit = useCan("audit.read");
  return (
    <>
      <PageHead title="Пользователи и настройки" />
      <div className="split">
        <div>
          <CompanyCard />
          {canUsers ? <UsersCard /> : null}
          {canUsers ? <BackupsCard /> : null}
          {canUsers ? <AssistantCard /> : null}
          {canUsers ? <RecognitionCard /> : null}
          {canAudit ? <AuditCard /> : null}
        </div>
        <AccountCard />
      </div>
    </>
  );
}
