"use client";

import { api, errorText, formatRub } from "@islamic-car/shared";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useClientApi } from "@/lib/useClientApi";

type Intent = {
  id: string; contract_id: string; contract_number: string | null; amount_kopecks: number; provider: string;
  test_mode: boolean; status: string; confirmation_url: string;
};

const STATUS: Record<string, { title: string; tone: string; text: string }> = {
  pending: { title: "Ожидаем подтверждения оплаты", tone: "warn", text: "Проверяем статус у платёжного сервиса. Страница обновится сама." },
  succeeded: { title: "Оплата получена", tone: "ok", text: "Платёж учтён, остаток по договору уменьшен." },
  canceled: { title: "Оплата отменена", tone: "danger", text: "Деньги не списаны. Можно попробовать ещё раз или оплатить по реквизитам." },
  failed: { title: "Платёжный сервис недоступен", tone: "danger", text: "Попробуйте позже или оплатите по реквизитам." },
  expired: { title: "Оплата не завершена", tone: "danger", text: "Если деньги списаны, напишите нам — мы проверим." },
  needs_review: { title: "Оплата получена, проверяем", tone: "warn",
    text: "Платёжный сервис подтвердил оплату, но автоматически учесть её не удалось. Сотрудник проверит и учтёт платёж." },
};

export default function PaymentStatusPage() {
  const { id } = useParams<{ id: string }>();
  const { data: intent, error, setData } = useClientApi<Intent>(`/api/client/online-payments/${id}`, 4000);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (error && !intent) return <div className="notice danger">{error}</div>;
  if (!intent) return <p>Загрузка…</p>;
  const st = STATUS[intent.status] ?? STATUS.pending;

  async function simulate(result: "succeeded" | "canceled") {
    setBusy(true);
    setErr(null);
    try {
      setData(await api<Intent>(`/api/client/online-payments/${id}/sandbox`, { method: "POST", json: { result } }));
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p><Link href={`/cabinet/contracts/${intent.contract_id}`}>← К договору № {intent.contract_number}</Link></p>
      <h1>Онлайн-оплата {formatRub(intent.amount_kopecks)}</h1>
      <div className={`notice ${st.tone}`}><strong>{st.title}</strong> {st.text}</div>

      {intent.test_mode && intent.status === "pending" ? (
        <div className="panel">
          <h2>Тестовая оплата</h2>
          <p className="small muted">Это тестовый режим для проверки системы: деньги не списываются. В рабочей системе здесь была бы страница банка.</p>
          {err ? <div className="form-error">{err}</div> : null}
          <div className="actions">
            <button className="btn btn-primary" disabled={busy} onClick={() => simulate("succeeded")}>Оплатить (тест)</button>
            <button className="btn" disabled={busy} onClick={() => simulate("canceled")}>Отменить</button>
          </div>
        </div>
      ) : null}

      {!intent.test_mode && intent.status === "pending" && intent.confirmation_url ? (
        <p><a className="btn" href={intent.confirmation_url}>Вернуться на страницу оплаты</a></p>
      ) : null}
    </>
  );
}
