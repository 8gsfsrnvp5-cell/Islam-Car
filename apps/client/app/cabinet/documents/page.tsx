"use client";

import { DOC_STATUS, formatDate, formatDateTime } from "@islamic-car/shared";

import { useClientApi } from "@/lib/useClientApi";

type MyDoc = { id: string; title: string; status: string; contract_id: string; contract_number: string; signed_on: string | null;
  final: boolean; created_at: string };

export default function MyDocumentsPage() {
  const { data, error } = useClientApi<MyDoc[]>("/api/client/documents");
  return (
    <>
      <h1>Документы</h1>
      <p className="muted">Документы по вашим договорам, которые утверждены продавцом или подписаны сторонами.</p>
      {error ? <div className="notice danger">{error}</div> : null}
      <div className="panel">
        {!data ? <p>Загрузка…</p> : !data.length ? <p className="muted">Документов пока нет.</p> : data.map((d) => (
          <div className="list-item" key={d.id}>
            <div>
              <strong>{d.title}</strong>
              <div className="small muted">
                Договор № {d.contract_number} · {d.signed_on ? `подписан ${formatDate(d.signed_on)}` : `${DOC_STATUS[d.status]} ${formatDateTime(d.created_at)}`}
                {d.final ? "" : " · проект"}
              </div>
            </div>
            <div className="actions">
              <a className="btn btn-sm" href={`/api/client/documents/${d.id}/export?format=pdf`}>PDF</a>
              <a className="btn btn-sm" href={`/api/client/documents/${d.id}/export?format=docx`}>DOCX</a>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
