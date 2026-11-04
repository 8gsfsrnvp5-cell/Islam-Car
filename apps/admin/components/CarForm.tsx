"use client";

import { CAR_STATUS, OWNERSHIP, type StaffCar, kopecksToInput, rublesToKopecks } from "@islamic-car/shared";
import { useState } from "react";

import { Field } from "@/components/ui";

type Values = Record<string, string>;

const TEXT_FIELDS = ["vin", "make", "model", "year", "mileage_km", "body_type", "engine", "transmission", "drive", "color",
  "trim", "condition", "description", "ownership_status", "status", "purchase_date", "purchase_document", "purchased_from",
  "max_term_months"] as const;
const MONEY_FIELDS = ["purchase_price_kopecks", "sale_price_kopecks", "min_down_payment_kopecks"] as const;

function initial(car?: StaffCar): Values {
  const v: Values = {};
  for (const f of TEXT_FIELDS) v[f] = car ? String((car as Record<string, unknown>)[f] ?? "") : "";
  for (const f of MONEY_FIELDS) v[f] = car ? kopecksToInput((car as Record<string, unknown>)[f] as number | null) : "";
  if (!car) { v.ownership_status = "purchasing"; v.status = "draft"; v.purchased_from = "unknown"; }
  return v;
}

/** Собирает тело запроса. Возвращает строку с ошибкой, если ввод некорректен. */
function toPayload(v: Values, canCost: boolean, isEdit: boolean): Record<string, unknown> | string {
  const out: Record<string, unknown> = {};
  for (const f of TEXT_FIELDS) out[f] = v[f].trim();
  for (const f of ["year", "mileage_km", "max_term_months"]) out[f] = v[f] === "" ? null : Number(v[f]);
  if (out.mileage_km === null) out.mileage_km = 0;
  out.vin = v.vin.trim() ? v.vin.trim().toUpperCase() : null;
  out.purchase_date = v.purchase_date || null;
  for (const f of MONEY_FIELDS) {
    const k = rublesToKopecks(v[f]);
    if (Number.isNaN(k)) return "Суммы указываются в рублях, например 1 600 000";
    out[f] = k;
  }
  if (!out.sale_price_kopecks) return "Укажите цену продажи";
  if (!canCost) delete out.purchase_price_kopecks;
  if (isEdit && out.status === "sold") delete out.status;
  return out;
}

export function CarForm({ car, canCost, busy, onSubmit, submitLabel }: {
  car?: StaffCar; canCost: boolean; busy: boolean; submitLabel: string;
  onSubmit: (payload: Record<string, unknown>) => void;
}) {
  const [v, setV] = useState<Values>(() => initial(car));
  const [error, setError] = useState<string | null>(null);
  const sold = car?.status === "sold";
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setV((prev) => ({ ...prev, [k]: e.target.value }));

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const payload = toPayload(v, canCost, Boolean(car));
    if (typeof payload === "string") { setError(payload); return; }
    setError(null);
    if (sold) {
      for (const f of ["vin", "sale_price_kopecks", "purchase_price_kopecks", "status", "ownership_status"]) delete payload[f];
    }
    onSubmit(payload);
  }

  return (
    <form onSubmit={submit}>
      <h3 style={{ margin: "0 0 10px" }}>Автомобиль</h3>
      <div className="form-grid">
        <Field label="Марка"><input value={v.make} onChange={set("make")} required /></Field>
        <Field label="Модель"><input value={v.model} onChange={set("model")} required /></Field>
        <Field label="Год выпуска"><input type="number" min={1980} max={2100} value={v.year} onChange={set("year")} required /></Field>
        <Field label="Пробег, км"><input type="number" min={0} value={v.mileage_km} onChange={set("mileage_km")} /></Field>
        <Field label="VIN" hint="17 символов. Обязателен для автомобиля в собственности.">
          <input value={v.vin} onChange={set("vin")} maxLength={17} className="mono" disabled={sold} />
        </Field>
        <Field label="Цвет"><input value={v.color} onChange={set("color")} /></Field>
        <Field label="Кузов"><input value={v.body_type} onChange={set("body_type")} placeholder="седан, кроссовер…" /></Field>
        <Field label="Двигатель"><input value={v.engine} onChange={set("engine")} placeholder="2.5 л, 181 л.с., бензин" /></Field>
        <Field label="Коробка передач"><input value={v.transmission} onChange={set("transmission")} /></Field>
        <Field label="Привод"><input value={v.drive} onChange={set("drive")} /></Field>
        <Field label="Комплектация" wide><textarea value={v.trim} onChange={set("trim")} /></Field>
        <Field label="Состояние" wide><textarea value={v.condition} onChange={set("condition")} /></Field>
        <Field label="Описание для каталога" wide><textarea value={v.description} onChange={set("description")} /></Field>
      </div>

      <h3 style={{ margin: "20px 0 10px" }}>Собственность и статус</h3>
      <div className="form-grid">
        <Field label="Право собственности" hint="«В наличии» показывается покупателям только для автомобиля в собственности">
          <select value={v.ownership_status} onChange={set("ownership_status")} disabled={sold}>
            {Object.entries(OWNERSHIP).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select>
        </Field>
        <Field label="Статус продажи">
          <select value={v.status} onChange={set("status")} disabled={sold}>
            {Object.entries(CAR_STATUS).filter(([k]) => k !== "sold" || sold).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select>
        </Field>
        <Field label="Дата покупки продавцом"><input type="date" value={v.purchase_date} onChange={set("purchase_date")} /></Field>
        <Field label="Документ о покупке" hint="Например: ДКП № 15 от 01.10.2026. Нужен для подписания договора.">
          <input value={v.purchase_document} onChange={set("purchase_document")} />
        </Field>
        <Field label="У кого куплен" hint="Влияет на порядок НДС при продаже (межценовая разница — для купленных у физлиц)">
          <select value={v.purchased_from} onChange={set("purchased_from")}>
            <option value="unknown">не указано</option>
            <option value="individual">у физического лица</option>
            <option value="company">у организации или ИП</option>
          </select>
        </Field>
      </div>

      <h3 style={{ margin: "20px 0 10px" }}>Цены и условия</h3>
      <div className="form-grid">
        {canCost ? (
          <Field label="Закупочная стоимость, ₽" hint="Коммерческая тайна: не показывается в каталоге">
            <input value={v.purchase_price_kopecks} onChange={set("purchase_price_kopecks")} inputMode="decimal" disabled={sold} />
          </Field>
        ) : null}
        <Field label="Окончательная цена продажи, ₽" hint="Фиксированная цена. Без процентов за рассрочку.">
          <input value={v.sale_price_kopecks} onChange={set("sale_price_kopecks")} inputMode="decimal" required disabled={sold} />
        </Field>
        <Field label="Минимальный первоначальный взнос, ₽"><input value={v.min_down_payment_kopecks} onChange={set("min_down_payment_kopecks")} inputMode="decimal" /></Field>
        <Field label="Максимальный срок рассрочки, мес."><input type="number" min={1} max={120} value={v.max_term_months} onChange={set("max_term_months")} /></Field>
      </div>
      {error ? <div className="form-error">{error}</div> : null}
      <div className="actions" style={{ marginTop: 16 }}>
        <button className="btn btn-primary" disabled={busy}>{busy ? "Сохранение…" : submitLabel}</button>
      </div>
    </form>
  );
}
