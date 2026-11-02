"use client";

import { type StaffCar, type StaffContract, api, formatDate, formatRub, kopecksToInput, rublesToKopecks } from "@islamic-car/shared";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import type { ClientData } from "@/components/ClientForm";
import { Card, ErrorBox, Field, Loading, Notice, PageHead } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Preview = {
  sale_price_kopecks: number; down_payment_kopecks: number; financed_kopecks: number; term_months: number;
  monthly_payment_kopecks: number; purchase_price_kopecks?: number; markup_kopecks?: number; car_owned: boolean;
  schedule: { seq: number; kind: string; due_date: string; amount_kopecks: number }[];
};

function isoToday(offsetMonths = 0): string {
  const d = new Date();
  d.setMonth(d.getMonth() + offsetMonths);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function NewContractForm() {
  const router = useRouter();
  const params = useSearchParams();
  const clients = useApi<ClientData[]>("/api/admin/clients");
  const cars = useApi<StaffCar[]>("/api/admin/cars");
  const [clientId, setClientId] = useState(params.get("client") ?? "");
  const [carId, setCarId] = useState(params.get("car") ?? "");
  const [sale, setSale] = useState("");
  const [down, setDown] = useState("");
  const [term, setTerm] = useState("12");
  const [contractDate, setContractDate] = useState(isoToday());
  const [firstDate, setFirstDate] = useState(isoToday(1));
  const [disclose, setDisclose] = useState(true);
  const [preview, setPreview] = useState<Preview | null>(null);
  const action = useAction();

  const sellable = useMemo(() => (cars.data ?? []).filter((c) => !["sold", "archived"].includes(c.status)), [cars.data]);
  const car = sellable.find((c) => c.id === carId);

  useEffect(() => {
    // Цена по умолчанию — из карточки автомобиля
    if (car && !sale) setSale(kopecksToInput(car.sale_price_kopecks));
  }, [car, sale]);

  function body() {
    const saleK = rublesToKopecks(sale);
    const downK = rublesToKopecks(down) ?? 0;
    if (!saleK || Number.isNaN(saleK) || Number.isNaN(downK)) throw new Error("Проверьте суммы: указываются в рублях");
    return { sale_price_kopecks: saleK, down_payment_kopecks: downK, term_months: Number(term),
      contract_date: contractDate, first_payment_date: firstDate };
  }

  async function calc() {
    const p = await action.run(() => api<Preview>("/api/admin/contracts/preview", { method: "POST", json: { car_id: carId, ...body() } }));
    if (p) setPreview(p);
  }

  async function create() {
    const c = await action.run(() => api<StaffContract>("/api/admin/contracts", {
      method: "POST",
      json: { client_id: clientId, car_id: carId, application_id: params.get("application") || null, disclose_cost_to_buyer: disclose, ...body() },
    }));
    if (c) router.push(`/contracts/${c.id}`);
  }

  if (clients.loading || cars.loading) return <Loading />;

  return (
    <>
      <PageHead title="Новый договор" subtitle="Сначала создаётся черновик. Система проверит данные и условия, после подписания график фиксируется." />
      <Notice tone="info" title="Как формируется цена">
        Цена продажи фиксируется в договоре и не меняется. Проценты за рассрочку и штрафы за просрочку не начисляются.
        Остаток после первоначального взноса делится на равные ежемесячные платежи (округление до рубля — в последнем платеже).
      </Notice>
      <ErrorBox error={action.error ?? clients.error ?? cars.error} />
      <div className="split">
        <Card title="Стороны и условия">
          <div className="form-grid">
            <Field label="Покупатель" wide>
              <select value={clientId} onChange={(e) => setClientId(e.target.value)} required>
                <option value="">— выберите клиента —</option>
                {clients.data?.map((c) => <option key={c.id} value={c.id}>{c.full_name} {c.identity_verified ? "" : "(личность не проверена)"}</option>)}
              </select>
            </Field>
            <Field label="Автомобиль" wide hint={car && car.ownership_status !== "owned" ? "Автомобиль ещё не в собственности — черновик можно подготовить, подписать нельзя." : undefined}>
              <select value={carId} onChange={(e) => { setCarId(e.target.value); setSale(""); setPreview(null); }} required>
                <option value="">— выберите автомобиль —</option>
                {sellable.map((c) => <option key={c.id} value={c.id}>{c.make} {c.model}, {c.year} · {c.vin ?? "без VIN"} · {formatRub(c.sale_price_kopecks)}</option>)}
              </select>
            </Field>
            <Field label="Окончательная цена продажи, ₽"><input value={sale} onChange={(e) => { setSale(e.target.value); setPreview(null); }} inputMode="decimal" /></Field>
            <Field label="Первоначальный взнос, ₽"><input value={down} onChange={(e) => { setDown(e.target.value); setPreview(null); }} inputMode="decimal" placeholder="0" /></Field>
            <Field label="Срок, месяцев"><input type="number" min={1} max={120} value={term} onChange={(e) => { setTerm(e.target.value); setPreview(null); }} /></Field>
            <Field label="Дата договора"><input type="date" value={contractDate} onChange={(e) => { setContractDate(e.target.value); setPreview(null); }} /></Field>
            <Field label="Дата первого ежемесячного платежа" hint="Следующие — в тот же день каждого месяца"><input type="date" value={firstDate} onChange={(e) => { setFirstDate(e.target.value); setPreview(null); }} /></Field>
            <label className="check wide">
              <input type="checkbox" checked={disclose} onChange={(e) => setDisclose(e.target.checked)} />
              <span>Раскрыть покупателю закупочную стоимость и наценку (принцип мурабахи)</span>
            </label>
          </div>
          <div className="actions" style={{ marginTop: 16 }}>
            <button className="btn" onClick={calc} disabled={!carId || action.busy}>Рассчитать график</button>
            <button className="btn btn-primary" onClick={create} disabled={!clientId || !carId || !preview || action.busy}>Создать черновик договора</button>
          </div>
        </Card>
        <Card title="Расчёт">
          {!preview ? <p className="muted">Выберите автомобиль, укажите условия и нажмите «Рассчитать график».</p> : (
            <>
              <dl className="kv">
                {preview.purchase_price_kopecks !== undefined ? <><dt>Закупочная стоимость</dt><dd>{formatRub(preview.purchase_price_kopecks)}</dd></> : null}
                {preview.markup_kopecks !== undefined ? <><dt>Торговая наценка</dt><dd>{formatRub(preview.markup_kopecks)}</dd></> : null}
                <dt>Цена продажи</dt><dd><strong>{formatRub(preview.sale_price_kopecks)}</strong></dd>
                <dt>Первоначальный взнос</dt><dd>{formatRub(preview.down_payment_kopecks)}</dd>
                <dt>Остаток к оплате</dt><dd>{formatRub(preview.financed_kopecks)}</dd>
                <dt>Ежемесячный платёж</dt><dd><strong>{formatRub(preview.monthly_payment_kopecks)}</strong> × {preview.term_months}</dd>
              </dl>
              {!preview.car_owned ? <Notice tone="warn">Автомобиль не в собственности продавца — подписание будет заблокировано.</Notice> : null}
              <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto", marginTop: 12 }}>
                <table>
                  <thead><tr><th>№</th><th>Дата</th><th className="num">Сумма</th></tr></thead>
                  <tbody>
                    {preview.schedule.map((r) => (
                      <tr key={r.seq}><td>{r.seq === 0 ? "Взнос" : r.seq}</td><td>{formatDate(r.due_date)}</td><td className="num">{formatRub(r.amount_kopecks)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      </div>
    </>
  );
}

export default function NewContractPage() {
  return <Suspense fallback={<Loading />}><NewContractForm /></Suspense>;
}
