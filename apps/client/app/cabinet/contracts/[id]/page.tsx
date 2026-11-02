"use client";

import {
  CONTRACT_STATUS, REPORT_STATUS, ROW_STATUS, type ClientContract, api, errorText, formatDate, formatRub, rublesToKopecks,
} from "@islamic-car/shared";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useClientApi } from "@/lib/useClientApi";

const ROW_TONE: Record<string, string> = { paid: "ok", overdue: "danger", due_today: "warn", partial: "warn", upcoming: "" };

type OnlineStatus = { enabled: boolean; provider: string; test_mode: boolean };

function OnlinePay({ contractId, suggested }: { contractId: string; suggested: number }) {
  const online = useClientApi<OnlineStatus>("/api/client/online-payment");
  const [amount, setAmount] = useState(suggested ? String(suggested / 100) : "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!online.data?.enabled) return null;

  async function pay(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const kopecks = rublesToKopecks(amount);
    if (!kopecks || Number.isNaN(kopecks)) { setErr("Укажите сумму в рублях"); return; }
    setBusy(true);
    try {
      const intent = await api<{ id: string; confirmation_url: string }>(`/api/client/contracts/${contractId}/online-payments`,
        { method: "POST", json: { amount_kopecks: kopecks } });
      window.location.href = intent.confirmation_url;  // страница оплаты платёжного сервиса (или тестовая страница)
    } catch (ex) {
      setErr(errorText(ex));
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>Оплатить онлайн</h2>
      {online.data.test_mode ? <div className="notice warn">Тестовый режим: деньги не списываются.</div> : null}
      <p className="small muted">Платёж учтётся автоматически, как только платёжный сервис подтвердит оплату. Комиссию за перевод вы не платите,
        проценты не начисляются.</p>
      <form className="form" onSubmit={pay}>
        <div className="form-row">
          <label className="field"><span>Сумма, ₽</span><input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" required /></label>
        </div>
        {err ? <div className="form-error">{err}</div> : null}
        <div><button className="btn btn-primary" disabled={busy}>{busy ? "Переход к оплате…" : "Перейти к оплате"}</button></div>
      </form>
    </div>
  );
}

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function ContractPage() {
  const { id } = useParams<{ id: string }>();
  const { data: c, error, reload } = useClientApi<ClientContract>(`/api/client/contracts/${id}`, 30000);
  const docs = useClientApi<{ id: string; title: string; contract_id: string; signed_on: string | null; final: boolean }[]>("/api/client/documents");
  const changes = useClientApi<{ number: number; signed_on: string; term_months: number }[]>(`/api/client/contracts/${id}/schedule-changes`);
  const [report, setReport] = useState({ amount: "", paid_on: todayIso(), comment: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  if (error && !c) return <div className="notice danger">{error}</div>;
  if (!c) return <p>Загрузка…</p>;
  const lg = c.ledger;

  async function sendReport(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const amount = rublesToKopecks(report.amount);
    if (!amount || Number.isNaN(amount)) { setFormError("Укажите сумму в рублях"); return; }
    try {
      await api(`/api/client/contracts/${id}/payment-reports`, { method: "POST", json: { amount_kopecks: amount, paid_on: report.paid_on, comment: report.comment } });
      setReport({ amount: "", paid_on: todayIso(), comment: "" });
      setMsg("Спасибо! Мы проверим поступление и учтём платёж. Остаток обновится после подтверждения.");
      reload();
    } catch (err) {
      setFormError(errorText(err));
    }
  }

  return (
    <>
      <p><Link href="/cabinet">← Мои договоры</Link></p>
      <h1>{c.car.title}</h1>
      <p className="muted">Договор № {c.number} от {formatDate(c.signed_at)} · <span className={`badge ${c.status === "completed" ? "ok" : ""}`}>{CONTRACT_STATUS[c.status]}</span></p>

      <div className="stats">
        <div className="stat"><span>Цена договора</span><strong>{formatRub(lg.total_kopecks)}</strong></div>
        <div className="stat ok"><span>Оплачено</span><strong>{formatRub(lg.paid_kopecks)}</strong></div>
        <div className="stat"><span>Остаток долга</span><strong>{formatRub(lg.outstanding_kopecks)}</strong></div>
        <div className={`stat ${lg.overdue_kopecks ? "danger" : ""}`}>
          <span>{lg.overdue_kopecks ? "Просрочено" : "Следующий платёж"}</span>
          <strong>{lg.overdue_kopecks ? formatRub(lg.overdue_kopecks) : lg.next_due_date ? formatRub(lg.next_due_kopecks) : "—"}</strong>
          {lg.next_due_date ? <span>{lg.overdue_kopecks ? `с ${formatDate(lg.oldest_overdue_date)}` : `до ${formatDate(lg.next_due_date)}`}</span> : null}
        </div>
      </div>
      {lg.overdue_kopecks ? (
        <div className="notice warn">
          По договору есть неоплаченная сумма {formatRub(lg.overdue_kopecks)}. Проценты и штрафы не начисляются.
          Если возникли трудности, <Link href={`/cabinet/support?topic=payment_difficulty&contract=${c.id}`}>напишите нам</Link> — обсудим решение.
        </div>
      ) : null}

      <div className="panel">
        <h2>Условия договора</h2>
        <dl className="kv">
          <dt>Автомобиль</dt><dd>{c.car.title}, {c.car.color}</dd>
          <dt>VIN</dt><dd className="mono">{c.car.vin}</dd>
          {c.purchase_price_kopecks !== undefined ? <><dt>Закупочная стоимость продавца</dt><dd>{formatRub(c.purchase_price_kopecks)}</dd></> : null}
          {c.markup_kopecks !== undefined ? <><dt>Наценка продавца</dt><dd>{formatRub(c.markup_kopecks)}</dd></> : null}
          <dt>Окончательная цена</dt><dd><strong>{formatRub(c.sale_price_kopecks)}</strong></dd>
          <dt>Первоначальный взнос</dt><dd>{formatRub(c.down_payment_kopecks)}</dd>
          <dt>Ежемесячный платёж</dt><dd>{formatRub(c.monthly_payment_kopecks)} × {c.term_months} мес.</dd>
          <dt>За просрочку</dt><dd>проценты, пени и штрафы не начисляются</dd>
        </dl>
      </div>

      <div className="panel">
        <div className="actions" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>График платежей</h2>
          <div className="actions">
            <a className="btn btn-sm" href={`/api/client/contracts/${c.id}/schedule.csv`}>Скачать график</a>
            <a className="btn btn-sm" href={`/api/client/contracts/${c.id}/statement.csv`}>Выписка по платежам</a>
          </div>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>№</th><th>Срок</th><th className="num">Сумма</th><th className="num">Оплачено</th><th>Статус</th></tr></thead>
            <tbody>
              {lg.rows?.map((r) => (
                <tr key={r.seq}>
                  <td>{r.seq === 0 ? "Взнос" : r.seq}</td>
                  <td>{formatDate(r.due_date)}</td>
                  <td className="num">{formatRub(r.amount_kopecks)}</td>
                  <td className="num">{formatRub(r.paid_kopecks)}</td>
                  <td><span className={`badge ${ROW_TONE[r.status]}`}>{ROW_STATUS[r.status]}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {changes.data?.length ? (
        <div className="notice info">
          {changes.data.map((ch) => (
            <div key={ch.number}>График изменён дополнительным соглашением № {ch.number} от {formatDate(ch.signed_on)}. Цена договора не изменилась.</div>
          ))}
        </div>
      ) : null}

      {docs.data?.some((d) => d.contract_id === c.id) ? (
        <div className="panel">
          <h2>Документы по договору</h2>
          {docs.data.filter((d) => d.contract_id === c.id).map((d) => (
            <div className="list-item" key={d.id}>
              <span>{d.title}{d.signed_on ? <span className="small muted"> · подписан {formatDate(d.signed_on)}</span> : null}</span>
              <a className="btn btn-sm" href={`/api/client/documents/${d.id}/export?format=pdf`}>Скачать PDF</a>
            </div>
          ))}
        </div>
      ) : null}

      <div className="panel">
        <h2>История оплат</h2>
        {!c.payments?.length ? <p className="muted">Подтверждённых платежей пока нет.</p> : c.payments.map((p) => (
          <div className="list-item" key={p.id}><span>{formatDate(p.received_on)}</span><strong>{formatRub(p.amount_kopecks)}</strong></div>
        ))}
        {c.reports?.length ? (
          <>
            <h3 style={{ marginTop: 16 }}>Ваши сообщения об оплате</h3>
            {c.reports.map((r) => (
              <div className="list-item" key={r.id}>
                <span>{formatRub(r.amount_kopecks)} от {formatDate(r.paid_on)}{r.review_note && r.status === "rejected" ? <div className="small muted">{r.review_note}</div> : null}</span>
                <span className={`badge ${r.status === "matched" ? "ok" : r.status === "rejected" ? "danger" : "warn"}`}>{REPORT_STATUS[r.status]}</span>
              </div>
            ))}
          </>
        ) : null}
      </div>

      {c.status === "signed" ? <OnlinePay contractId={c.id} suggested={lg.overdue_kopecks || lg.next_due_kopecks} /> : null}

      {c.status === "signed" ? (
        <div className="panel">
          <h2>Я оплатил</h2>
          <p className="small muted">Сообщите о переводе — мы быстрее найдём платёж. Платёж будет учтён после поступления денег и проверки сотрудником.
            Реквизиты — в разделе <Link href="/cabinet/payment">«Как оплатить»</Link>.</p>
          {msg ? <div className="notice ok">{msg}</div> : null}
          <form className="form" onSubmit={sendReport}>
            <div className="form-row">
              <label className="field"><span>Сумма, ₽</span><input value={report.amount} onChange={(e) => setReport({ ...report, amount: e.target.value })} inputMode="decimal" required /></label>
              <label className="field"><span>Дата оплаты</span><input type="date" value={report.paid_on} onChange={(e) => setReport({ ...report, paid_on: e.target.value })} required /></label>
            </div>
            <label className="field"><span>Комментарий</span><input value={report.comment} onChange={(e) => setReport({ ...report, comment: e.target.value })} placeholder="Например: перевод из Сбербанка" /></label>
            {formError ? <div className="form-error">{formError}</div> : null}
            <div><button className="btn btn-primary">Сообщить об оплате</button></div>
          </form>
        </div>
      ) : null}

      {c.status === "signed" ? (
        <div className="actions">
          <Link className="btn" href={`/cabinet/support?topic=early_repayment&contract=${c.id}`}>Запросить досрочное погашение</Link>
          <Link className="btn" href={`/cabinet/support?topic=schedule_change&contract=${c.id}`}>Попросить изменить график</Link>
        </div>
      ) : null}
    </>
  );
}
