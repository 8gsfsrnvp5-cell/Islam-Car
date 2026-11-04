"use client";

import { type StaffCar, api, formatDate, formatRub, rublesToKopecks } from "@islamic-car/shared";
import Link from "next/link";
import { useCallback, useState } from "react";

import { PositionCard, ProfitabilityCard, ScenariosCard } from "@/components/FinanceV3";
import { useCan } from "@/components/Shell";
import { Card, Empty, ErrorBox, Field, Loading, Notice, PageHead } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Expense = { id: string; spent_on: string; category: string; amount_kopecks: number; description: string; car_id: string | null; document_ref: string };
type CarResult = {
  contract_id: string; number: string; car: string; client: string; purchase_price_kopecks: number; sale_price_kopecks: number;
  markup_kopecks: number; car_expenses_kopecks: number; markup_after_car_expenses_kopecks: number; received_kopecks: number;
  outstanding_kopecks: number; overdue_kopecks: number; cost_recovered_kopecks: number;
};

const CATEGORIES = ["Аренда", "Зарплата", "Реклама", "Подготовка автомобиля", "Транспортировка", "Связь и сервисы", "Юридические услуги", "Прочее"];

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function FinancePage() {
  const canFinance = useCan("finance.read");
  const canWrite = useCan("expenses.write");
  const results = useApi<CarResult[]>(canFinance ? "/api/admin/finance/cars" : null);
  const expenses = useApi<Expense[]>(canFinance ? "/api/admin/expenses" : null);
  const cars = useApi<StaffCar[]>(canFinance ? "/api/admin/cars" : null);
  const [form, setForm] = useState({ spent_on: todayIso(), category: CATEGORIES[0], amount: "", description: "", car_id: "", document_ref: "" });
  const action = useAction();
  const [contracts, setContracts] = useState<{ number: string; client: string }[]>([]);
  const onPosition = useCallback((p: { contracts: { number: string; client: string }[] }) => setContracts(p.contracts), []);

  if (!canFinance) return <><PageHead title="Финансы" /><Notice tone="warn">Недостаточно прав для просмотра финансовых данных.</Notice></>;

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const amount = rublesToKopecks(form.amount);
    if (!amount || Number.isNaN(amount)) { action.setError("Укажите сумму в рублях"); return; }
    const r = await action.run(() => api("/api/admin/expenses", { method: "POST", json: {
      spent_on: form.spent_on, category: form.category, amount_kopecks: amount, description: form.description,
      car_id: form.car_id || null, document_ref: form.document_ref } }));
    if (r) { setForm({ ...form, amount: "", description: "", document_ref: "" }); expenses.reload(); results.reload(); }
  }

  const carTitle = (id: string | null) => {
    const c = cars.data?.find((x) => x.id === id);
    return c ? `${c.make} ${c.model}` : "";
  };

  return (
    <>
      <PageHead title="Финансы" subtitle="Деньги, резерв, сценарии, расходы и результат по каждому проданному автомобилю" />
      <PositionCard onLoaded={onPosition} />
      <ScenariosCard contracts={contracts} />
      <ProfitabilityCard />

      <Card title="Результат по проданным автомобилям" subtitle="Наценка — по условиям договора; «Вернулось вложений» — по фактически поступившим деньгам" flush>
        <ErrorBox error={results.error} />
        {results.loading && !results.data ? <Loading /> : !results.data?.length ? <Empty>Подписанных договоров нет</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Договор / автомобиль</th><th className="num">Закупка</th><th className="num">Продажа</th><th className="num">Наценка</th>
                <th className="num">Расходы на авто</th><th className="num">Наценка за вычетом</th><th className="num">Поступило</th><th className="num">Вернулось вложений</th><th className="num">Остаток долга</th></tr></thead>
              <tbody>
                {results.data.map((r) => (
                  <tr key={r.contract_id}>
                    <td><Link href={`/contracts/${r.contract_id}`}>№ {r.number}</Link><div className="small muted">{r.car} · {r.client}</div></td>
                    <td className="num">{formatRub(r.purchase_price_kopecks)}</td>
                    <td className="num">{formatRub(r.sale_price_kopecks)}</td>
                    <td className="num">{formatRub(r.markup_kopecks)}</td>
                    <td className="num">{formatRub(r.car_expenses_kopecks)}</td>
                    <td className="num"><strong>{formatRub(r.markup_after_car_expenses_kopecks)}</strong></td>
                    <td className="num">{formatRub(r.received_kopecks)}</td>
                    <td className="num">{formatRub(r.cost_recovered_kopecks)}</td>
                    <td className="num">{formatRub(r.outstanding_kopecks)}{r.overdue_kopecks ? <div className="small" style={{ color: "var(--danger)" }}>просрочено {formatRub(r.overdue_kopecks)}</div> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="split">
        <Card title="Расходы" flush>
          <ErrorBox error={expenses.error} />
          {expenses.loading && !expenses.data ? <Loading /> : !expenses.data?.length ? <Empty>Расходы не внесены</Empty> : (
            <table>
              <thead><tr><th>Дата</th><th>Категория</th><th>Описание</th><th className="num">Сумма</th></tr></thead>
              <tbody>
                {expenses.data.map((x) => (
                  <tr key={x.id}>
                    <td>{formatDate(x.spent_on)}</td>
                    <td>{x.category}{x.car_id ? <div className="small muted">{carTitle(x.car_id)}</div> : null}</td>
                    <td className="small">{x.description}{x.document_ref ? <div className="muted">{x.document_ref}</div> : null}</td>
                    <td className="num">{formatRub(x.amount_kopecks)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        {canWrite ? (
          <Card title="Внести расход">
            <form onSubmit={add} className="grid">
              <Field label="Дата"><input type="date" value={form.spent_on} onChange={(e) => setForm({ ...form, spent_on: e.target.value })} required /></Field>
              <Field label="Категория">
                <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
                </select>
              </Field>
              <Field label="Сумма, ₽"><input value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} inputMode="decimal" required /></Field>
              <Field label="Относится к автомобилю" hint="Для расчёта результата по конкретной машине">
                <select value={form.car_id} onChange={(e) => setForm({ ...form, car_id: e.target.value })}>
                  <option value="">— общий расход —</option>
                  {cars.data?.map((c) => <option key={c.id} value={c.id}>{c.make} {c.model}, {c.year} {c.vin ?? ""}</option>)}
                </select>
              </Field>
              <Field label="Описание"><input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
              <Field label="Подтверждающий документ"><input value={form.document_ref} onChange={(e) => setForm({ ...form, document_ref: e.target.value })} /></Field>
              <ErrorBox error={action.error} />
              <button className="btn btn-primary" disabled={action.busy}>Добавить расход</button>
            </form>
          </Card>
        ) : null}
      </div>
    </>
  );
}
