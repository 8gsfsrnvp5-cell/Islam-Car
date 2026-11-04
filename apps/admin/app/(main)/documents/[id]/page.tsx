"use client";

import { DOC_STATUS, type DocItem, api, formatDate, formatDateTime } from "@islamic-car/shared";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useState } from "react";

import { ReasonButton } from "@/components/Confirm";
import { DocChecks, DocumentPaper } from "@/components/DocumentView";
import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Field, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function DocumentPage() {
  const { id } = useParams<{ id: string }>();
  const canWrite = useCan("contracts.write");
  const canSign = useCan("contracts.sign");
  const { data: doc, error, setData } = useApi<DocItem>(`/api/admin/documents/${id}`);
  const action = useAction();
  const [signedOn, setSignedOn] = useState(todayIso());
  const [confirmed, setConfirmed] = useState(false);
  const [file, setFile] = useState<File | null>(null);

  if (!doc) return error ? <ErrorBox error={error} /> : <Loading />;

  const post = async (path: string, json?: unknown) => {
    const r = await action.run(() => api<DocItem>(`/api/admin/documents/${id}/${path}`, { method: "POST", json }));
    if (r) setData(r);
  };

  async function markSigned(e: React.FormEvent) {
    e.preventDefault();
    const body = new FormData();
    body.append("signed_on", signedOn);
    body.append("confirm_paper_signed", String(confirmed));
    if (file) body.append("file", file);
    const r = await action.run(() => api<DocItem>(`/api/admin/documents/${id}/signed`, { method: "POST", body }));
    if (r) setData(r);
  }

  return (
    <>
      <PageHead
        title={doc.title}
        subtitle={<><StatusBadge status={doc.status} labels={DOC_STATUS} /> · шаблон {doc.template_code} v{doc.template_version} · создан {formatDateTime(doc.created_at)}
          {doc.contract_id ? <> · <Link href={`/contracts/${doc.contract_id}`}>договор</Link></> : null}</>}
        actions={
          <>
            <a className="btn" href={`/api/admin/documents/${id}/export?format=pdf`}>PDF</a>
            <a className="btn" href={`/api/admin/documents/${id}/export?format=docx`}>DOCX</a>
            {doc.has_signed_file ? <a className="btn" href={`/api/admin/documents/${id}/signed-file`} target="_blank" rel="noreferrer">Скан подписанного</a> : null}
          </>
        }
      />
      <ErrorBox error={action.error} />
      {!doc.template_approved ? (
        <Notice tone="warn" title="Шаблон не утверждён юристом">
          Документ — проект. Его можно обсуждать и согласовывать, но окончательной версии и фиксации подписания не будет,
          пока шаблон не утвердит юрист (раздел «Документы и шаблоны» → «Шаблоны»).
        </Notice>
      ) : null}
      {doc.status === "signed" ? <Notice tone="ok" title={`Подписан ${formatDate(doc.signed_on)}`}>Документ неизменяем. Контрольная сумма текста: <span className="mono">{doc.body_sha256.slice(0, 16)}…</span></Notice> : null}
      {doc.status === "cancelled" ? <Notice tone="danger" title="Отменён">{doc.cancelled_reason}</Notice> : null}

      <div className="split">
        <DocumentPaper blocks={doc.blocks ?? []} watermark={doc.watermark} />
        <div>
          <Card title="Проверки"><DocChecks checks={doc.checks} /></Card>
          <Card title="Действия">
            <div className="grid">
              {doc.status === "draft" && canWrite ? (
                <>
                  <button className="btn" onClick={() => post("regenerate")} disabled={action.busy}>Обновить из карточек</button>
                  <button className="btn btn-primary" onClick={() => post("submit")} disabled={action.busy}>Передать на утверждение</button>
                </>
              ) : null}
              {doc.status === "pending_approval" && canSign ? (
                <button className="btn btn-primary" onClick={() => post("approve")} disabled={action.busy}>Утвердить документ</button>
              ) : null}
              {doc.status === "approved" && canSign ? (
                <form onSubmit={markSigned} className="inline-form">
                  <Notice tone="info">Подписи и печати система не создаёт. Здесь фиксируется факт подписания сторонами; скан можно приложить.</Notice>
                  <Field label="Дата подписания"><input type="date" value={signedOn} onChange={(e) => setSignedOn(e.target.value)} required /></Field>
                  <Field label="Скан подписанного документа (PDF, JPEG, PNG)"><input type="file" accept="application/pdf,image/jpeg,image/png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
                  <label className="check"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /><span className="small">Документ подписан сторонами</span></label>
                  <button className="btn btn-primary" disabled={!confirmed || action.busy}>Зафиксировать подписание</button>
                </form>
              ) : null}
              {doc.status !== "signed" && doc.status !== "cancelled" && canWrite ? (
                <ReasonButton label="Отменить документ" placeholder="Причина отмены" submitLabel="Отменить" onSubmit={(reason) => post("cancel", { reason })} danger />
              ) : null}
            </div>
            {doc.params && Object.keys(doc.params).length ? (
              <dl className="kv small" style={{ marginTop: 14 }}>
                {Object.entries(doc.params).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{String(v) || "—"}</dd></Fragment>)}
              </dl>
            ) : null}
          </Card>
        </div>
      </div>
    </>
  );
}
