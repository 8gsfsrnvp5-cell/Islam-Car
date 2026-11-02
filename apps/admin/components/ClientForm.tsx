"use client";

import { PARTY_TYPE } from "@islamic-car/shared";
import { useState } from "react";

import { Field } from "@/components/ui";

export type ClientData = {
  id: string; party_type: string; full_name: string; phone: string; email: string; address: string;
  birth_date: string | null; passport_number: string; passport_issued_by: string; passport_issue_date: string | null;
  inn: string; ogrn: string; kpp: string; representative: string; timezone: string; notes: string;
  identity_verified: boolean; identity_verified_at: string | null; has_cabinet_access: boolean;
  cabinet_login: string | null; created_at: string; pd_masked: boolean;
};

const FIELDS = ["party_type", "full_name", "phone", "email", "address", "birth_date", "passport_number", "passport_issued_by",
  "passport_issue_date", "inn", "ogrn", "kpp", "representative", "timezone", "notes"] as const;

const PD_FIELDS = ["phone", "address", "birth_date", "passport_number", "passport_issued_by", "passport_issue_date"];

export function ClientForm({ client, busy, onSubmit, submitLabel }: {
  client?: ClientData; busy: boolean; submitLabel: string; onSubmit: (payload: Record<string, unknown>) => void;
}) {
  const [v, setV] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of FIELDS) init[f] = client ? String(client[f] ?? "") : "";
    if (!client) { init.party_type = "individual"; init.timezone = "Europe/Moscow"; }
    return init;
  });
  const masked = Boolean(client?.pd_masked);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setV((prev) => ({ ...prev, [k]: e.target.value }));

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const payload: Record<string, unknown> = {};
    for (const f of FIELDS) {
      if (masked && PD_FIELDS.includes(f)) continue; // маскированные данные не отправляем обратно
      payload[f] = v[f].trim();
    }
    for (const f of ["birth_date", "passport_issue_date"]) if (f in payload && !payload[f]) payload[f] = null;
    onSubmit(payload);
  }

  const type = v.party_type;
  return (
    <form onSubmit={submit}>
      <div className="form-grid">
        <Field label="Тип покупателя">
          <select value={v.party_type} onChange={set("party_type")}>
            {Object.entries(PARTY_TYPE).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select>
        </Field>
        <Field label={type === "llc" ? "Наименование организации" : "ФИО полностью"}>
          <input value={v.full_name} onChange={set("full_name")} required minLength={2} />
        </Field>
        <Field label="Телефон"><input value={v.phone} onChange={set("phone")} required disabled={masked} /></Field>
        <Field label="Электронная почта"><input type="email" value={v.email} onChange={set("email")} /></Field>
        <Field label={type === "llc" ? "Юридический адрес" : "Адрес регистрации"} wide>
          <input value={v.address} onChange={set("address")} disabled={masked} />
        </Field>
        {type === "individual" ? (
          <>
            <Field label="Дата рождения"><input type="date" value={v.birth_date} onChange={set("birth_date")} disabled={masked} /></Field>
            <Field label="Паспорт: серия и номер"><input value={v.passport_number} onChange={set("passport_number")} disabled={masked} /></Field>
            <Field label="Кем выдан" wide><input value={v.passport_issued_by} onChange={set("passport_issued_by")} disabled={masked} /></Field>
            <Field label="Дата выдачи"><input type="date" value={v.passport_issue_date} onChange={set("passport_issue_date")} disabled={masked} /></Field>
            <Field label="ИНН (если есть)"><input value={v.inn} onChange={set("inn")} /></Field>
          </>
        ) : (
          <>
            <Field label="ИНН"><input value={v.inn} onChange={set("inn")} /></Field>
            <Field label={type === "ip" ? "ОГРНИП" : "ОГРН"}><input value={v.ogrn} onChange={set("ogrn")} /></Field>
            {type === "llc" ? (
              <>
                <Field label="КПП"><input value={v.kpp} onChange={set("kpp")} /></Field>
                <Field label="Представитель и основание полномочий"><input value={v.representative} onChange={set("representative")} /></Field>
              </>
            ) : null}
          </>
        )}
        <Field label="Часовой пояс" hint="Для уведомлений в допустимое время">
          <select value={v.timezone} onChange={set("timezone")}>
            {["Europe/Kaliningrad", "Europe/Moscow", "Europe/Samara", "Asia/Yekaterinburg", "Asia/Omsk", "Asia/Novosibirsk",
              "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk", "Asia/Vladivostok", "Asia/Magadan", "Asia/Kamchatka"].map((tz) => (
              <option key={tz} value={tz}>{tz}</option>
            ))}
          </select>
        </Field>
        <Field label="Заметки" wide><textarea value={v.notes} onChange={set("notes")} /></Field>
      </div>
      {masked ? <p className="small muted" style={{ marginTop: 8 }}>Персональные данные скрыты: недостаточно прав для просмотра.</p> : null}
      <div className="actions" style={{ marginTop: 16 }}>
        <button className="btn btn-primary" disabled={busy}>{busy ? "Сохранение…" : submitLabel}</button>
      </div>
    </form>
  );
}
