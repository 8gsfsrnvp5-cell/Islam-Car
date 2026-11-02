"use client";

import {
  CONTRACT_STATUS, PARTY_TYPE, PAYMENT_METHOD, PAYMENT_STATUS, REPORT_STATUS, ROW_STATUS, SELLER_REGIME, type PaymentReport,
  type StaffContract, api, formatDate, formatDateTime, formatRub, kopecksToInput, label, rublesToKopecks,
} from "@islamic-car/shared";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ConfirmButton, ReasonButton } from "@/components/Confirm";
import { useCan } from "@/components/Shell";
import { Badge, Card, ErrorBox, Field, Loading, Notice, PageHead, Stat, StatusBadge } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function ContractPage() {
  const { id } = useParams<{ id: string }>();
  const canSign = useCan("contracts.sign");
  const canWrite = useCan("contracts.write");
  const canConfirm = useCan("payments.confirm");
  const canReverse = useCan("payments.reverse");
  const { data: c, error, setData, reload } = useApi<StaffContract>(`/api/admin/contracts/${id}`);
  const action = useAction();
  const [signedOn, setSignedOn] = useState(todayIso());
  const [paperSigned, setPaperSigned] = useState(false);
  const [pay, setPay] = useState({ amount: "", received_on: todayIso(), method: "bank_transfer", document_ref: "", note: "", report_id: "" });
  const [notice, setNotice] = useState<string | null>(null);

  if (!c) return error ? <ErrorBox error={error} /> : <Loading />;
  const lg = c.ledger!;
  const live = c.status === "signed" || c.status === "completed";
  const pendingReports = (c.reports ?? []).filter((r) => r.status === "pending");

  async function sign(e: React.FormEvent) {
    e.preventDefault();
    const r = await action.run(() => api<StaffContract>(`/api/admin/contracts/${id}/sign`, {
      method: "POST", json: { signed_on: signedOn, confirm_paper_signed: paperSigned } }));
    if (r) { setData(r); setNotice(`Договор подписан, присвоен № ${r.number}. График зафиксирован.`); }
  }

  async function cancel() {
    const r = await action.run(() => api<StaffContract>(`/api/admin/contracts/${id}/cancel`, { method: "POST" }));
    if (r) setData(r);
  }

  async function confirmPayment(e: React.FormEvent) {
    e.preventDefault();
    const amount = rublesToKopecks(pay.amount);
    if (!amount || Number.isNaN(amount)) { action.setError("Укажите сумму в рублях"); return; }
    const r = await action.run(() => api(`/api/admin/payments`, { method: "POST", json: {
      contract_id: id, amount_kopecks: amount, received_on: pay.received_on, method: pay.method,
      document_ref: pay.document_ref, note: pay.note, report_id: pay.report_id || null } }));
    if (r) {
      setPay({ amount: "", received_on: todayIso(), method: "bank_transfer", document_ref: "", note: "", report_id: "" });
      setNotice("Платёж подтверждён и учтён. Остаток пересчитан, покупатель получил уведомление.");
      reload();
    }
  }

  async function reverse(paymentId: string, reason: string) {
    if (await action.run(() => api(`/api/admin/payments/${paymentId}/reverse`, { method: "POST", json: { reason } }))) {
      setNotice("Платёж сторнирован. Исходная запись сохранена, остаток пересчитан.");
      reload();
    }
  }

  async function rejectReport(r: PaymentReport, note: string) {
    if (await action.run(() => api(`/api/admin/payment-reports/${r.id}/reject`, { method: "POST", json: { note } }))) reload();
  }

  function takeReport(r: PaymentReport) {
    setPay({ ...pay, amount: kopecksToInput(r.amount_kopecks), received_on: r.paid_on, report_id: r.id });
  }

  return (
    <>
      <PageHead
        title={c.number ? `Договор № ${c.number}` : "Черновик договора"}
        subtitle={<><StatusBadge status={c.status} labels={CONTRACT_STATUS} /> · <Link href={`/clients/${c.client.id}`}>{c.client.full_name}</Link> · <Link href={`/cars/${c.car.id}`}>{c.car.title}</Link></>}
        actions={c.status === "draft" && canWrite ? (
          <ConfirmButton label="Отменить черновик" question="Отменить? Автомобиль снова станет доступен." confirmLabel="Отменить черновик"
                         onConfirm={cancel} danger disabled={action.busy} />
        ) : null}
      />
      <ErrorBox error={action.error} />
      {notice ? <Notice tone="ok">{notice}</Notice> : null}

      {live ? (
        <div className="grid grid-4" style={{ marginBottom: 16 }}>
          <Stat label="Цена договора" value={formatRub(lg.total_kopecks)} />
          <Stat label="Оплачено (подтверждено)" value={formatRub(lg.paid_kopecks)} tone="ok" />
          <Stat label="Остаток долга" value={formatRub(lg.outstanding_kopecks)} />
          <Stat label="Просрочено" value={formatRub(lg.overdue_kopecks)} tone={lg.overdue_kopecks ? "danger" : undefined}
                hint={lg.oldest_overdue_date ? `с ${formatDate(lg.oldest_overdue_date)}, без начислений` : "Без процентов и штрафов"} />
        </div>
      ) : null}

      <div className="split">
        <div>
          <Card title="Условия">
            <dl className="kv">
              <dt>Продавец</dt><dd>{label(SELLER_REGIME, c.seller_regime)}</dd>
              <dt>Покупатель</dt><dd>{label(PARTY_TYPE, c.buyer_type)} {c.is_consumer_deal ? <Badge tone="info">потребительская сделка</Badge> : null}</dd>
              <dt>Автомобиль</dt><dd>{c.car.title} <span className="mono small">{c.car.vin ?? "VIN не указан"}</span></dd>
              {c.purchase_price_kopecks !== undefined ? <><dt>Закупочная стоимость</dt><dd>{formatRub(c.purchase_price_kopecks)}</dd></> : null}
              {c.markup_kopecks !== undefined ? <><dt>Торговая наценка</dt><dd>{formatRub(c.markup_kopecks)}</dd></> : null}
              <dt>Окончательная цена</dt><dd><strong>{formatRub(c.sale_price_kopecks)}</strong></dd>
              <dt>Первоначальный взнос</dt><dd>{formatRub(c.down_payment_kopecks)}</dd>
              <dt>Остаток в рассрочку</dt><dd>{formatRub(c.financed_kopecks)}</dd>
              <dt>Ежемесячный платёж</dt><dd>{formatRub(c.monthly_payment_kopecks)} × {c.term_months} мес.</dd>
              <dt>Дата договора</dt><dd>{formatDate(c.contract_date)}{c.signed_at ? ` · подписан ${formatDate(c.signed_at)}` : ""}</dd>
              <dt>Раскрытие себестоимости</dt><dd>{c.disclose_cost_to_buyer ? "покупатель видит закупочную стоимость и наценку" : "не раскрывается"}</dd>
              <dt>Просрочка</dt><dd>проценты, пени и штрафы не начисляются</dd>
            </dl>
          </Card>

          <Card title="График платежей" subtitle={live ? "Платежи распределяются по порядку: сначала взнос, затем самые ранние" : "Черновик: график пересоздаётся при изменении условий"} flush>
            <div className="table-wrap">
              <table>
                <thead><tr><th>№</th><th>Срок</th><th className="num">Сумма</th>{live ? <><th className="num">Оплачено</th><th className="num">Остаток</th><th>Статус</th></> : null}</tr></thead>
                <tbody>
                  {live ? (lg.rows ?? []).map((r) => (
                    <tr key={r.seq}>
                      <td>{r.seq === 0 ? "Взнос" : r.seq}</td>
                      <td>{formatDate(r.due_date)}</td>
                      <td className="num">{formatRub(r.amount_kopecks)}</td>
                      <td className="num">{formatRub(r.paid_kopecks)}</td>
                      <td className="num">{formatRub(r.remaining_kopecks)}</td>
                      <td><StatusBadge status={r.status} labels={ROW_STATUS} /></td>
                    </tr>
                  )) : (c.schedule ?? []).map((r) => (
                    <tr key={r.seq}>
                      <td>{r.seq === 0 ? "Взнос" : r.seq}</td>
                      <td>{formatDate(r.due_date)}</td>
                      <td className="num">{formatRub(r.amount_kopecks)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {live ? (
            <Card title="Поступления" subtitle="Платёж не удаляется: ошибочный сторнируется с причиной, история сохраняется" flush>
              {!c.payments?.length ? <div className="empty">Поступлений пока нет</div> : (
                <table>
                  <thead><tr><th>Дата</th><th className="num">Сумма</th><th>Способ / документ</th><th>Статус</th><th></th></tr></thead>
                  <tbody>
                    {c.payments.map((p) => (
                      <tr key={p.id}>
                        <td>{formatDate(p.received_on)}<div className="small muted">внесён {formatDateTime(p.confirmed_at)}</div></td>
                        <td className="num">{p.status === "reversed" ? <s>{formatRub(p.amount_kopecks)}</s> : formatRub(p.amount_kopecks)}</td>
                        <td className="small">{label(PAYMENT_METHOD, p.method)}<div className="muted">{p.document_ref}{p.note ? ` · ${p.note}` : ""}</div>
                          {p.corrects_payment_id ? <div className="muted">исправляет ошибочную запись</div> : null}</td>
                        <td><StatusBadge status={p.status} labels={PAYMENT_STATUS} />{p.reversal_reason ? <div className="small muted">{p.reversal_reason}</div> : null}</td>
                        <td className="right">{p.status === "confirmed" && canReverse ? (
                          <ReasonButton label="Сторно" placeholder="Причина (сохранится в истории)" submitLabel="Сторнировать" minLength={5}
                                        onSubmit={(reason) => reverse(p.id, reason)} danger small disabled={action.busy} />
                        ) : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          ) : null}
        </div>

        <div>
          {c.status === "draft" && c.checks ? (
            <Card title="Проверки перед подписанием" subtitle="Блокирующие ошибки нужно устранить в карточках клиента, автомобиля или в настройках">
              <ul className="checks">
                {c.checks.items.map((it) => (
                  <li key={it.code}>
                    <span className={`mark ${it.info ? "warn" : it.ok ? "ok" : it.blocking ? "bad" : "warn"}`}>{it.info ? "i" : it.ok ? "✓" : it.blocking ? "✕" : "!"}</span>
                    <span className="small">{it.message}</span>
                  </li>
                ))}
              </ul>
              <div className="actions" style={{ marginTop: 10 }}>
                <button className="btn btn-sm" onClick={() => reload()}>Перепроверить</button>
              </div>
            </Card>
          ) : null}

          {c.status === "draft" && canSign ? (
            <Card title="Подписание">
              <Notice tone="info">
                Печатная форма договора из утверждённых юристом шаблонов появится в версии 2. Сейчас договор оформляется на бумаге,
                а здесь фиксируется факт подписания. Подписи и печати система не создаёт.
              </Notice>
              <form onSubmit={sign} className="grid">
                <Field label="Дата подписания"><input type="date" value={signedOn} onChange={(e) => setSignedOn(e.target.value)} required /></Field>
                <label className="check">
                  <input type="checkbox" checked={paperSigned} onChange={(e) => setPaperSigned(e.target.checked)} />
                  <span className="small">Подтверждаю, что договор подписан покупателем и продавцом</span>
                </label>
                <button className="btn btn-primary" disabled={!paperSigned || !c.checks?.can_sign || action.busy}>Зафиксировать подписание</button>
              </form>
            </Card>
          ) : null}

          {live ? (
            <Card title="Следующий платёж">
              {lg.next_due_date ? (
                <p><strong>{formatRub(lg.next_due_kopecks)}</strong> до {formatDate(lg.next_due_date)}</p>
              ) : <p className="muted">Все платежи по графику внесены.</p>}
            </Card>
          ) : null}

          {live && pendingReports.length ? (
            <Card title="Сообщения покупателя об оплате" subtitle="Не учитываются, пока платёж не найден в банке">
              {pendingReports.map((r) => (
                <div key={r.id} style={{ marginBottom: 10 }}>
                  <div><strong>{formatRub(r.amount_kopecks)}</strong> от {formatDate(r.paid_on)} <StatusBadge status={r.status} labels={REPORT_STATUS} /></div>
                  {r.comment ? <div className="small muted">{r.comment}</div> : null}
                  {canConfirm ? (
                    <div className="actions" style={{ marginTop: 6 }}>
                      <button className="btn btn-sm" onClick={() => takeReport(r)}>Платёж найден — заполнить форму</button>
                      <ReasonButton label="Не найден" placeholder="Сообщение покупателю" submitLabel="Отправить"
                                    onSubmit={(note) => rejectReport(r, note)} danger small disabled={action.busy} />
                    </div>
                  ) : null}
                </div>
              ))}
            </Card>
          ) : null}

          {c.status === "signed" && canConfirm ? (
            <Card title="Подтвердить поступление" subtitle="Только по банковской выписке или кассовому документу">
              <form onSubmit={confirmPayment} className="grid">
                {pay.report_id ? <Notice tone="info">Связано с сообщением покупателя об оплате.</Notice> : null}
                <Field label="Сумма, ₽" hint={`Остаток долга: ${formatRub(lg.outstanding_kopecks)}`}>
                  <input value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} inputMode="decimal" required />
                </Field>
                <Field label="Дата поступления"><input type="date" value={pay.received_on} onChange={(e) => setPay({ ...pay, received_on: e.target.value })} required /></Field>
                <Field label="Способ">
                  <select value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}>
                    {Object.entries(PAYMENT_METHOD).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
                  </select>
                </Field>
                <Field label="Документ" hint="Номер платёжного поручения, ПКО или чека">
                  <input value={pay.document_ref} onChange={(e) => setPay({ ...pay, document_ref: e.target.value })} required />
                </Field>
                <Field label="Комментарий"><input value={pay.note} onChange={(e) => setPay({ ...pay, note: e.target.value })} /></Field>
                <button className="btn btn-primary" disabled={action.busy}>Подтвердить платёж</button>
              </form>
            </Card>
          ) : null}
        </div>
      </div>
    </>
  );
}
