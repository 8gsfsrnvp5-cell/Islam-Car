"use client";

import { api } from "@islamic-car/shared";
import Link from "next/link";
import { useState } from "react";

import { Badge, Card, ErrorBox, Loading, Notice, PageHead } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Status = {
  enabled: boolean; configured: boolean; model: string; reason: string; can_use: boolean; can_manage: boolean;
  data_scope: string; disclaimer: string;
};
type Source = { code: string; library: string; title: string; act: string; article: string; source_url: string; reliable: boolean; problems: string[] };
type Answer = {
  question_sent: string; removed: string[]; answer: string; sources: Source[]; verdict: string; warnings: string[];
  disclaimer: string; model: string;
};

export default function AssistantPage() {
  const status = useApi<Status>("/api/admin/assistant");
  const [question, setQuestion] = useState("");
  const [preview, setPreview] = useState<{ question: string; removed: string[] } | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const action = useAction();

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const r = await action.run(() => api<{ question: string; removed: string[] }>("/api/admin/assistant/preview", { method: "POST", json: { question } }));
    if (r) setPreview(r);
  }

  async function sendReviewed() {
    if (!preview) return;
    const r = await action.run(() => api<Answer>("/api/admin/assistant/ask", { method: "POST", json: { question, reviewed_question: preview.question } }));
    if (r) { setAnswer(r); setPreview(null); }
  }

  const st = status.data;
  return (
    <>
      <PageHead title="Помощник по нормам" subtitle="Черновые формулировки со ссылками на записи библиотек знаний" />
      <ErrorBox error={status.error} />
      {!st ? <Loading /> : (
        <>
          <Notice tone="warn" title="Ответ помощника — не заключение специалиста">
            {st.disclaimer} Надёжность оснований определяет система по заключениям юриста, бухгалтера и специалиста по шариату.
            Ставки, сроки и суммы помощник берёт только из записей библиотек — если их там нет, он об этом скажет.
          </Notice>
          {!st.enabled ? (
            <Notice tone="info" title="Помощник выключен">
              {st.reason}. {st.can_manage ? <>Включить можно в разделе <Link href="/settings">«Пользователи и настройки»</Link>.</>
                : "Включает владелец."}
            </Notice>
          ) : !st.can_use ? (
            <Notice tone="warn">Для вашей роли помощник недоступен.</Notice>
          ) : (
            <Card title="Вопрос" subtitle={st.data_scope}>
              <form onSubmit={ask}>
                <textarea value={question} onChange={(e) => { setQuestion(e.target.value); setPreview(null); }} disabled={action.busy} rows={4} minLength={5} maxLength={2000}
                          placeholder="Например: можно ли продлить срок рассрочки дополнительным соглашением и сохранить цену?"
                          style={{ width: "100%" }} required />
                <p className="small muted">Не указывайте ФИО, телефоны, паспортные данные, номера договоров: они вырезаются автоматически,
                  но проверка не идеальна.</p>
                <ErrorBox error={action.error} />
                <button className="btn btn-primary" disabled={action.busy || question.trim().length < 5}>
                  {action.busy ? "Проверяю…" : "Проверить перед отправкой"}</button>
              </form>
              {preview ? <Notice tone="warn" title="Проверьте текст для отправки в Claude API">
                <p style={{ whiteSpace: "pre-wrap" }}>{preview.question}</p>
                <p>Если остались имена, адреса или другие персональные данные, исправьте вопрос выше.</p>
                <button type="button" className="btn btn-primary" disabled={action.busy} onClick={sendReviewed}>
                  {action.busy ? "Готовлю ответ…" : "Данных клиентов нет — отправить"}
                </button>
              </Notice> : null}
            </Card>
          )}
          {answer ? (
            <Card title="Ответ" subtitle={`Модель: ${answer.model}`}>
              {answer.verdict ? <Notice tone="warn" title={answer.verdict}>
                Основания не подтверждены специалистом или их недостаточно. Используйте ответ только как подсказку для вопроса специалисту.
              </Notice> : <Notice tone="ok">Все цитируемые записи подтверждены специалистами. Окончательное решение — за специалистом.</Notice>}
              {answer.warnings.map((w) => <Notice key={w} tone="danger">{w}</Notice>)}
              <p style={{ whiteSpace: "pre-wrap" }}>{answer.answer}</p>
              <h3 style={{ fontSize: 14, marginTop: 16 }}>Основания</h3>
              {!answer.sources.length ? <p className="small muted">Помощник не сослался ни на одну запись.</p> : (
                <table>
                  <tbody>
                    {answer.sources.map((s) => (
                      <tr key={s.code}>
                        <td className="mono small">{s.code}</td>
                        <td>{s.title}<div className="small muted">{s.act} {s.article}</div></td>
                        <td>{s.reliable ? <Badge tone="ok">Проверено</Badge> : <Badge tone="warn">Требуется проверка</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="small muted" style={{ marginTop: 12 }}>
                Отправленный вопрос: «{answer.question_sent}»{answer.removed.length ? ` · вырезано: ${answer.removed.join(", ")}` : ""}
              </p>
            </Card>
          ) : null}
        </>
      )}
    </>
  );
}
