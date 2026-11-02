"use client";

import {
  BANK_TX_STATUS, type BankImport, type BankTransaction, type StaffContract, api, formatDate, formatDateTime, formatRub,
} from "@islamic-car/shared";
import Link from "next/link";
import { useState } from "react";

import { ReasonButton } from "@/components/Confirm";
import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Loading, Notice, PageHead, type Tone } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

const TX_TONE: Record<string, Tone> = { new: "warn", suggested: "info", confirmed: "ok", ignored: undefined };

function ConfirmRow({ tx, contracts, onDone }: { tx: BankTransaction; contracts: StaffContract[]; onDone: () => void }) {
  const [contractId, setContractId] = useState(tx.match_contract_id ?? "");
  const action = useAction();
  const confirm = async () => {
    if (await action.run(() => api(`/api/admin/bank/transactions/${tx.id}/confirm`,
      { method: "POST", json: { contract_id: contractId } }))) onDone();
  };
  const ignore = async (reason: string) => {
    if (await action.run(() => api(`/api/admin/bank/transactions/${tx.id}/ignore`,
      { method: "POST", json: { reason } }))) onDone();
  };
  return (
    <div className="actions" style={{ justifyContent: "flex-end", flexWrap: "wrap" }}>
      <select value={contractId} onChange={(e) => setContractId(e.target.value)} aria-label="Договор" style={{ maxWidth: 260 }}>
        <option value="">— выберите договор —</option>
        {contracts.map((c) => (
          <option key={c.id} value={c.id}>№ {c.number} · {c.client.full_name} · остаток {formatRub(c.ledger?.outstanding_kopecks)}</option>
        ))}
      </select>
      <button className="btn btn-sm btn-primary" onClick={confirm} disabled={!contractId || action.busy}>Учесть платёж</button>
      <ReasonButton label="Не относится" placeholder="Причина (например, возврат поставщика)" minLength={5}
                    onSubmit={ignore} small disabled={action.busy} />
      {action.error ? <div className="small" style={{ color: "var(--danger)", width: "100%", textAlign: "right" }}>{action.error}</div> : null}
    </div>
  );
}

export default function BankPage() {
  const canImport = useCan("payments.import");
  const canConfirm = useCan("payments.confirm");
  const [filter, setFilter] = useState<"open" | "all">("open");
  const txs = useApi<BankTransaction[]>(`/api/admin/bank/transactions${filter === "open" ? "?status=open" : ""}`);
  const imports = useApi<BankImport[]>("/api/admin/bank/imports");
  const contracts = useApi<StaffContract[]>(canConfirm ? "/api/admin/contracts?status=signed" : null);
  const upload = useAction();
  const reopen = useAction();
  const [result, setResult] = useState<BankImport | null>(null);
  const [file, setFile] = useState<File | null>(null);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    const r = await upload.run(() => api<BankImport>("/api/admin/bank/imports", { method: "POST", body }));
    if (r) { setResult(r); setFile(null); (e.target as HTMLFormElement).reset(); txs.reload(); imports.reload(); }
  }
  const reload = () => { txs.reload(); contracts.reload(); };

  return (
    <>
      <PageHead title="Банковские выписки" subtitle="Загрузка выписки из интернет-банка и сверка поступлений с договорами"
                actions={<a className="btn btn-sm" href="/api/admin/reports/bank.xlsx">Выгрузить в Excel</a>} />
      <Notice tone="info">
        Система предлагает договор для каждого поступления и объясняет, почему. Долг покупателя уменьшается только после того,
        как сотрудник нажмёт «Учесть платёж». Сумма больше остатка долга не учитывается — переплату оформите отдельно.
      </Notice>

      {canImport ? (
        <Card title="Загрузить выписку" subtitle="Формат обмена с 1С (файл kl_to_1c.txt): выгружается в любом интернет-банке. Кодировка определяется автоматически">
          <form onSubmit={send} className="actions">
            <input type="file" accept=".txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="Файл выписки" />
            <button className="btn btn-primary" disabled={!file || upload.busy}>Загрузить</button>
          </form>
          <ErrorBox error={upload.error} />
          {result ? (
            <Notice tone="ok" title="Выписка загружена">
              Документов в файле: {result.rows_total}, входящих: {result.rows_incoming}, новых поступлений: {result.rows_new}
              {result.rows_incoming > result.rows_new ? " (остальные уже были загружены раньше)" : ""}.
            </Notice>
          ) : null}
        </Card>
      ) : null}

      <Card title="Поступления" flush actions={
        <div className="actions">
          <button className={`btn btn-sm ${filter === "open" ? "btn-primary" : ""}`} onClick={() => setFilter("open")}>Ждут решения</button>
          <button className={`btn btn-sm ${filter === "all" ? "btn-primary" : ""}`} onClick={() => setFilter("all")}>Все</button>
        </div>
      }>
        <ErrorBox error={txs.error ?? reopen.error} />
        {txs.loading && !txs.data ? <Loading /> : !txs.data?.length ? (
          <Empty>{filter === "open" ? "Все поступления разобраны" : "Выписки ещё не загружались"}</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Поступило</th><th className="num">Сумма</th><th>Плательщик и назначение</th><th>Совпадение</th><th></th></tr></thead>
              <tbody>
                {txs.data.map((t) => (
                  <tr key={t.id}>
                    <td>{formatDate(t.received_on)}<div className="small muted">п/п № {t.doc_number} от {formatDate(t.doc_date)}</div></td>
                    <td className="num"><strong>{formatRub(t.amount_kopecks)}</strong></td>
                    <td style={{ maxWidth: 360 }}>
                      {t.payer_name}{t.payer_inn ? <span className="small muted"> · ИНН {t.payer_inn}</span> : null}
                      <div className="small muted">{t.purpose}</div>
                    </td>
                    <td style={{ maxWidth: 280 }}>
                      <Badge tone={TX_TONE[t.status]}>{BANK_TX_STATUS[t.status]}</Badge>
                      {t.match_contract_id ? (
                        <div className="small"><Link href={`/contracts/${t.match_contract_id}`}>№ {t.match_contract_number}</Link>
                          {t.status !== "confirmed" ? <span className="muted"> · {t.match_score} баллов</span> : null}</div>
                      ) : null}
                      {t.status !== "confirmed" && t.match_reasons.length ? (
                        <ul className="small muted" style={{ margin: "4px 0 0", paddingLeft: 16 }}>
                          {t.match_reasons.map((r) => <li key={r}>{r}</li>)}
                        </ul>
                      ) : null}
                      {t.note ? <div className="small muted">{t.note}</div> : null}
                    </td>
                    <td className="right" style={{ minWidth: 300 }}>
                      {canConfirm && (t.status === "new" || t.status === "suggested") ? (
                        <ConfirmRow tx={t} contracts={contracts.data ?? []} onDone={reload} />
                      ) : canConfirm && t.status === "ignored" ? (
                        <button className="btn btn-sm" disabled={reopen.busy} onClick={async () => {
                          if (await reopen.run(() => api(`/api/admin/bank/transactions/${t.id}/reopen`, { method: "POST" }))) txs.reload();
                        }}>Вернуть в работу</button>
                      ) : t.reviewed_at ? <span className="small muted">{formatDateTime(t.reviewed_at)}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Загруженные выписки" flush>
        <ErrorBox error={imports.error} />
        {!imports.data?.length ? <Empty>Пока нет</Empty> : (
          <table>
            <thead><tr><th>Загружена</th><th>Файл</th><th>Период</th><th>Счёт</th><th className="num">Входящих</th><th className="num">Новых</th></tr></thead>
            <tbody>
              {imports.data.map((i) => (
                <tr key={i.id}>
                  <td className="small">{formatDateTime(i.created_at)}</td>
                  <td className="small">{i.file_name}</td>
                  <td className="small">{formatDate(i.period_from)} — {formatDate(i.period_to)}</td>
                  <td className="small mono">{i.account ? `…${i.account.slice(-4)}` : "—"}</td>
                  <td className="num">{i.rows_incoming}</td>
                  <td className="num">{i.rows_new}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
