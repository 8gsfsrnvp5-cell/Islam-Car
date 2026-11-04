import { formatRub } from "@islamic-car/shared";
import type { ReactNode } from "react";

export function PageHead({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {actions ? <div className="actions">{actions}</div> : null}
    </div>
  );
}

export function Card({ title, subtitle, actions, children, flush }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean;
}) {
  return (
    <section className="card">
      {title ? (
        <div className="card-head">
          <div>
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          {actions ? <div className="actions">{actions}</div> : null}
        </div>
      ) : null}
      <div className={flush ? "card-body flush" : "card-body"}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "ok" | "warn" | "danger" }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

export type Tone = "ok" | "warn" | "danger" | "info" | "brand" | undefined;

export function Badge({ tone, children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge ${tone ?? ""}`}>{children}</span>;
}

const TONES: Record<string, Tone> = {
  // заявки
  new: "warn", in_progress: "info", info_requested: "info", offer_made: "brand", converted: "ok", rejected: "danger", withdrawn: undefined,
  // договоры
  draft: undefined, signed: "brand", completed: "ok", cancelled: undefined,
  // строки графика
  paid: "ok", partial: "info", overdue: "danger", due_today: "warn", upcoming: undefined,
  // платежи и сообщения
  confirmed: "ok", reversed: "danger", pending: "warn", matched: "ok",
  // автомобили
  available: "ok", reserved: "warn", sold: "brand", archived: undefined, owned: "ok", purchasing: "warn",
  // обращения
  open: "warn", answered: "info", closed: undefined,
  // документы, сообщения, залоги, задачи
  pending_approval: "warn", approved: "info", scheduled: "info", sent: "ok", failed: "danger", skipped: undefined,
  documents_prepared: "info", submitted: "info", registered: "ok", release_required: "danger",
  release_submitted: "warn", released: undefined, not_required: undefined, planned: "warn", done: "ok",
};

export function StatusBadge({ status, labels }: { status: string; labels: Record<string, string> }) {
  return <Badge tone={TONES[status]}>{labels[status] ?? status}</Badge>;
}

export function Money({ k, strong }: { k: number | null | undefined; strong?: boolean }) {
  return strong ? <strong>{formatRub(k)}</strong> : <>{formatRub(k)}</>;
}

export function Field({ label, hint, children, wide }: { label: string; hint?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`field ${wide ? "wide" : ""}`}>
      <span>{label}</span>
      {children}
      {hint ? <small>{hint}</small> : null}
    </label>
  );
}

export function Notice({ tone, title, children }: { tone?: "info" | "warn" | "danger" | "ok"; title?: string; children?: ReactNode }) {
  return (
    <div className={`notice ${tone ?? ""}`}>
      {title ? <strong>{title}</strong> : null}
      {children}
    </div>
  );
}

export function Loading() {
  return <div className="empty">Загрузка…</div>;
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <Notice tone="danger" title="Ошибка">{error}</Notice>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

/** Окно из ТЗ, которое относится к следующим версиям. Никаких выдуманных данных. */
export function Planned({ title, version, purpose, items }: { title: string; version: number; purpose: string; items: string[] }) {
  return (
    <>
      <PageHead title={title} subtitle={purpose} />
      <Notice tone="warn" title={`Не реализовано в версии 1 — запланировано в версии ${version}`}>
        Окно создано, чтобы закрепить структуру системы. Функции ещё не работают, поэтому здесь не показываются никакие
        данные — ни настоящие, ни примерные.
      </Notice>
      <Card title="Что будет в этом окне">
        <ul>
          {items.map((it) => <li key={it}>{it}</li>)}
        </ul>
      </Card>
    </>
  );
}
