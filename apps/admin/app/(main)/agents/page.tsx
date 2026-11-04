"use client";

import { api, formatDateTime } from "@islamic-car/shared";
import Link from "next/link";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, ErrorBox, Loading, Notice, PageHead } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type FindingT = { severity: string; title: string; message: string; link: string; refs: string[]; suggestion: string };
type Run = { id: string; status: string; started_at: string; finished_at: string | null; counts: Record<string, number>;
  findings?: FindingT[]; actions?: { action: string; title: string; created?: boolean }[]; error?: string; manual: boolean };
type AgentT = { code: string; title: string; description: string; permissions: string[]; reads: string[]; last_run: Run | null };
type Listing = { agents: AgentT[]; mode: string; principles: string[] };

const SEV: Record<string, { tone: "danger" | "warn" | "info"; label: string }> = {
  critical: { tone: "danger", label: "Критично" }, warning: { tone: "warn", label: "Внимание" }, info: { tone: "info", label: "Сведения" },
};
const PERM: Record<string, string> = { "create:tasks": "создавать задачи", "create:staff_notifications": "уведомлять сотрудников" };

export default function AgentsPage() {
  const canRun = useCan("agents.run");
  const { data, error, reload } = useApi<Listing>("/api/admin/agents");
  const [open, setOpen] = useState<string | null>(null);
  const action = useAction();
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;

  const run = async (code: string) => { if (await action.run(() => api(`/api/admin/agents/${code}/run`, { method: "POST" }))) { setOpen(code); reload(); } };

  return (
    <>
      <PageHead title="Центр ИИ-агентов" subtitle={`Режим: ${data.mode}. Ежедневный запуск — фоновым обработчиком в 07:00.`} />
      <Notice tone="info" title="Принципы">
        <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{data.principles.map((p) => <li key={p} className="small">{p}</li>)}</ul>
      </Notice>
      <ErrorBox error={action.error} />
      {data.agents.map((a) => {
        const r = a.last_run;
        return (
          <Card key={a.code} title={a.title} subtitle={a.description}
                actions={<>{canRun ? <button className="btn btn-sm" onClick={() => run(a.code)} disabled={action.busy}>Запустить</button> : null}
                  <button className="btn btn-sm" onClick={() => setOpen(open === a.code ? null : a.code)}>{open === a.code ? "Скрыть" : "Выводы"}</button></>}>
            <div className="actions small">
              <span className="muted">Читает: {a.reads.join(", ")}.</span>
              <span className="muted">Может: {a.permissions.length ? a.permissions.map((p) => PERM[p] ?? p).join(", ") : "только сообщать выводы"}.</span>
            </div>
            {r ? (
              <div className="actions small" style={{ marginTop: 8 }}>
                <span>Последний запуск: {formatDateTime(r.started_at)}{r.manual ? " (вручную)" : ""}</span>
                {r.status === "failed" ? <Badge tone="danger">ошибка</Badge> : null}
                {r.counts.critical ? <Badge tone="danger">критично: {r.counts.critical}</Badge> : null}
                {r.counts.warning ? <Badge tone="warn">внимание: {r.counts.warning}</Badge> : null}
                {r.counts.info ? <Badge tone="info">сведения: {r.counts.info}</Badge> : null}
                {!r.counts.critical && !r.counts.warning && !r.counts.info && r.status === "ok" ? <Badge tone="ok">замечаний нет</Badge> : null}
              </div>
            ) : <p className="small muted" style={{ marginTop: 8 }}>Ещё не запускался.</p>}
            {open === a.code && r ? (
              <div style={{ marginTop: 10 }}>
                {r.error ? <Notice tone="danger" title="Ошибка запуска"><pre className="small" style={{ whiteSpace: "pre-wrap" }}>{r.error}</pre></Notice> : null}
                {(r.findings ?? []).map((f, i) => (
                  <div key={i} className={`notice ${SEV[f.severity]?.tone === "danger" ? "danger" : SEV[f.severity]?.tone === "warn" ? "warn" : "info"}`}>
                    <strong>{SEV[f.severity]?.label}: {f.link ? <Link href={f.link}>{f.title}</Link> : f.title}</strong>
                    {f.message ? <div className="small">{f.message}</div> : null}
                    {f.suggestion ? <div className="small">Рекомендация: {f.suggestion}</div> : null}
                    {f.refs.length ? <div className="small muted">Основания: {f.refs.map((c) => <Link key={c} href="/knowledge" className="mono">{c} </Link>)}</div> : null}
                  </div>
                ))}
                {r.actions?.length ? <p className="small muted">Действия агента: {r.actions.map((x) => `${x.action === "create_task" ? "задача" : "уведомление"} «${x.title}»${x.created === false ? " (уже была)" : ""}`).join("; ")}</p> : null}
              </div>
            ) : null}
          </Card>
        );
      })}
    </>
  );
}
