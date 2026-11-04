"use client";

import { CHANNEL, api, formatDateTime } from "@islamic-car/shared";
import { useState } from "react";

import { useCan } from "@/components/Shell";
import { Badge, Card, ErrorBox, Field } from "@/components/ui";
import { useAction, useApi } from "@/lib/useApi";

type Comms = {
  phone_verified: boolean; email_verified: boolean; email: string;
  consents: Record<string, { granted: boolean; source: string; recorded_at: string }>;
  history: { channel: string; granted: boolean; source: string; recorded_at: string }[];
};

export function ClientCommunications({ clientId }: { clientId: string }) {
  const canWrite = useCan("clients.write");
  const canVerify = useCan("clients.verify");
  const { data, error, setData } = useApi<Comms>(`/api/admin/clients/${clientId}/communications`);
  const [source, setSource] = useState("письменное согласие при заключении договора");
  const action = useAction();
  if (!data) return error ? <ErrorBox error={error} /> : null;

  const verify = async (contact: "phone" | "email", verified: boolean) => {
    const r = await action.run(() => api<Comms>(`/api/admin/clients/${clientId}/contacts/verify`, { method: "POST", json: { contact, verified } }));
    if (r) setData(r);
  };
  const consent = async (channel: string, granted: boolean) => {
    const r = await action.run(() => api<Comms>(`/api/admin/clients/${clientId}/consents`, { method: "POST", json: { channel, granted, source } }));
    if (r) setData(r);
  };

  return (
    <Card title="Связь и согласия" subtitle="Сведения о долге уходят только на подтверждённые контакты и только по разрешённым каналам">
      <ErrorBox error={action.error} />
      <table>
        <thead><tr><th>Канал</th><th>Контакт</th><th>Согласие</th></tr></thead>
        <tbody>
          {(["sms", "email"] as const).map((ch) => {
            const contact = ch === "sms" ? "phone" : "email";
            const verified = ch === "sms" ? data.phone_verified : data.email_verified;
            const c = data.consents[ch];
            return (
              <tr key={ch}>
                <td>{CHANNEL[ch]}</td>
                <td>
                  {verified ? <Badge tone="ok">подтверждён</Badge> : <Badge tone="warn">не подтверждён</Badge>}
                  {ch === "email" && !data.email ? <div className="small muted">e-mail не указан</div> : null}
                  {canVerify ? <div><button className="link-btn small" onClick={() => verify(contact, !verified)}>{verified ? "снять подтверждение" : "подтвердить"}</button></div> : null}
                </td>
                <td>
                  {c?.granted ? <Badge tone="ok">есть</Badge> : <Badge>нет</Badge>}
                  {c ? <div className="small muted">{c.source}, {formatDateTime(c.recorded_at)}</div> : null}
                  {canWrite ? <div><button className="link-btn small" onClick={() => consent(ch, !c?.granted)}>{c?.granted ? "отметить отзыв" : "отметить согласие"}</button></div> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {canWrite ? <Field label="Основание для отметки согласия"><input value={source} onChange={(e) => setSource(e.target.value)} /></Field> : null}
      <p className="small muted" style={{ marginTop: 6 }}>Уведомления в личном кабинете приходят всегда — согласие на них не требуется. История согласий хранится полностью.</p>
    </Card>
  );
}
