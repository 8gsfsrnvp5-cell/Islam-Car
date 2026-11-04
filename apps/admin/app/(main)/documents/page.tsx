"use client";

import { DOC_STATUS, type DocItem, type DocTemplate, api, formatDateTime } from "@islamic-car/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Field, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

function TemplatesTab() {
  const canApprove = useCan("settings.write");
  const { data, error, reload } = useApi<DocTemplate[]>("/api/admin/templates");
  const [open, setOpen] = useState<string | null>(null);
  const [lawyer, setLawyer] = useState("");
  const [note, setNote] = useState("");
  const action = useAction();

  async function approve(code: string) {
    if (await action.run(() => api(`/api/admin/templates/${code}/approve`, { method: "POST", json: { lawyer_name: lawyer, note } }))) {
      setOpen(null); setLawyer(""); setNote(""); reload();
    }
  }
  async function revoke(code: string) {
    if (await action.run(() => api(`/api/admin/templates/${code}/revoke`, { method: "POST" }))) reload();
  }

  return (
    <>
      <Notice tone="info" title="Как утверждаются шаблоны">
        Шаблоны лежат в репозитории (<code>templates/contracts</code>). Пометки «⚖ ЮРИСТ» — вопросы, которые юрист должен решить
        в тексте шаблона; пока они есть, шаблон утвердить нельзя. Утверждение привязано к точному содержимому файла: любое
        изменение текста снимает утверждение. Документы из неутверждённого шаблона остаются проектами с водяным знаком.
      </Notice>
      <ErrorBox error={error ?? action.error} />
      {!data ? <Loading /> : (
        <Card flush>
          <table>
            <thead><tr><th>Шаблон</th><th>Версия</th><th>Вопросы юристу</th><th>Статус</th><th></th></tr></thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.code}>
                  <td><strong>{t.title}</strong><div className="small muted">{t.description}</div>
                    {open === t.code ? (
                      <div className="inline-form" style={{ marginTop: 10, maxWidth: 420 }}>
                        <Field label="ФИО юриста, утвердившего текст"><input value={lawyer} onChange={(e) => setLawyer(e.target.value)} /></Field>
                        <Field label="Комментарий (реквизиты заключения, дата)"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
                        <div className="actions">
                          <button className="btn btn-primary btn-sm" disabled={lawyer.trim().length < 3 || action.busy} onClick={() => approve(t.code)}>Зафиксировать утверждение</button>
                          <button className="btn btn-sm" onClick={() => setOpen(null)}>Отмена</button>
                        </div>
                      </div>
                    ) : null}
                  </td>
                  <td className="mono small">{t.version}</td>
                  <td className="small">{t.lawyer_points.length ? <Badge tone="warn">{t.lawyer_points.length}</Badge> : <Badge tone="ok">нет</Badge>}</td>
                  <td>{t.approved ? <><Badge tone="ok">Утверждён</Badge><div className="small muted">{t.approval?.lawyer_name}, {formatDateTime(t.approval?.approved_at)}</div></>
                    : <Badge>Черновик</Badge>}</td>
                  <td className="right">
                    {canApprove && !t.approved && !t.lawyer_points.length && open !== t.code ? <button className="btn btn-sm" onClick={() => setOpen(t.code)}>Утвердить</button> : null}
                    {canApprove && t.approved ? <button className="btn btn-sm btn-danger" onClick={() => revoke(t.code)}>Снять утверждение</button> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}

function DocumentsTab() {
  const router = useRouter();
  const [status, setStatus] = useState("");
  const { data, error, loading } = useApi<DocItem[]>(`/api/admin/documents${status ? `?status=${status}` : ""}`);
  return (
    <>
      <div className="tabs">
        {["", "draft", "pending_approval", "approved", "signed", "cancelled"].map((s) => (
          <button key={s || "all"} className={status === s ? "active" : ""} onClick={() => setStatus(s)}>{s ? DOC_STATUS[s] : "Все"}</button>
        ))}
      </div>
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.length ? <Empty>Документов нет. Документы формируются из карточки договора.</Empty> : (
          <table>
            <thead><tr><th>Документ</th><th>Создан</th><th>Шаблон</th><th>Статус</th></tr></thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.id} className="clickable" onClick={() => router.push(`/documents/${d.id}`)}>
                  <td><strong>{d.title}</strong>{d.watermark ? <div className="small muted">{d.watermark}</div> : null}</td>
                  <td className="small">{formatDateTime(d.created_at)}</td>
                  <td className="small">{d.template_approved ? <Badge tone="ok">утверждён</Badge> : <Badge>черновик</Badge>}</td>
                  <td><StatusBadge status={d.status} labels={DOC_STATUS} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

export default function DocumentsPage() {
  const [tab, setTab] = useState<"docs" | "templates">("docs");
  return (
    <>
      <PageHead title="Документы и шаблоны" subtitle="Документы формируются только из шаблонов и проверенных данных карточек"
                actions={<Link className="btn" href="/contracts">К договорам</Link>} />
      <div className="tabs">
        <button className={tab === "docs" ? "active" : ""} onClick={() => setTab("docs")}>Документы</button>
        <button className={tab === "templates" ? "active" : ""} onClick={() => setTab("templates")}>Шаблоны</button>
      </div>
      {tab === "docs" ? <DocumentsTab /> : <TemplatesTab />}
    </>
  );
}
