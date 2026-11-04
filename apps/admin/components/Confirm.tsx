"use client";

import { useState } from "react";

/** Кнопка с подтверждением прямо на странице (вместо системного confirm). */
export function ConfirmButton({ label, question, confirmLabel = "Да", onConfirm, danger, small, disabled }: {
  label: string; question: string; confirmLabel?: string; onConfirm: () => void | Promise<void>;
  danger?: boolean; small?: boolean; disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const cls = `btn ${small ? "btn-sm" : ""}`;
  if (!asking) {
    return <button className={`${cls} ${danger ? "btn-danger" : ""}`} onClick={() => setAsking(true)} disabled={disabled}>{label}</button>;
  }
  return (
    <span className="actions" style={{ gap: 6 }}>
      <span className="small">{question}</span>
      <button className={`${cls} ${danger ? "btn-danger" : "btn-primary"}`} disabled={disabled}
              onClick={async () => { await onConfirm(); setAsking(false); }}>{confirmLabel}</button>
      <button className={cls} onClick={() => setAsking(false)}>Отмена</button>
    </span>
  );
}

/** Кнопка, которая просит ввести текст (причину, сообщение) перед действием. */
export function ReasonButton({ label, placeholder, submitLabel = "Подтвердить", minLength = 2, onSubmit, danger, small, disabled }: {
  label: string; placeholder: string; submitLabel?: string; minLength?: number;
  onSubmit: (text: string) => void | Promise<unknown>; danger?: boolean; small?: boolean; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const cls = `btn ${small ? "btn-sm" : ""}`;
  if (!open) {
    return <button className={`${cls} ${danger ? "btn-danger" : ""}`} onClick={() => setOpen(true)} disabled={disabled}>{label}</button>;
  }
  return (
    <form className="actions" style={{ gap: 6, justifyContent: "flex-end" }}
          onSubmit={async (e) => { e.preventDefault(); await onSubmit(text.trim()); setOpen(false); setText(""); }}>
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} minLength={minLength} required autoFocus style={{ minWidth: 220 }} />
      <button className={`${cls} ${danger ? "btn-danger" : "btn-primary"}`} disabled={disabled}>{submitLabel}</button>
      <button type="button" className={cls} onClick={() => setOpen(false)}>Отмена</button>
    </form>
  );
}
