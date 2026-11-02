"use client";

import { PARTY_TYPE, formatDate, label } from "@islamic-car/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { ClientData } from "@/components/ClientForm";
import { useCan } from "@/components/Shell";
import { Badge, Card, Empty, ErrorBox, Loading, PageHead } from "@/components/ui";
import { useApi } from "@/lib/useApi";

export default function ClientsPage() {
  const router = useRouter();
  const canWrite = useCan("clients.write");
  const [q, setQ] = useState("");
  const { data, error, loading } = useApi<ClientData[]>(`/api/admin/clients${q ? `?q=${encodeURIComponent(q)}` : ""}`);

  return (
    <>
      <PageHead title="Реестр клиентов" subtitle="Покупатели — физические лица, ИП и ООО"
                actions={canWrite ? <Link className="btn btn-primary" href="/clients/new">Новый клиент</Link> : null} />
      <input type="search" placeholder="ФИО, телефон, e-mail" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 320, marginBottom: 12 }} />
      <ErrorBox error={error} />
      <Card flush>
        {loading && !data ? <Loading /> : !data?.length ? <Empty>Клиентов нет</Empty> : (
          <table>
            <thead><tr><th>Клиент</th><th>Тип</th><th>Телефон</th><th>Личность</th><th>Личный кабинет</th><th>Добавлен</th></tr></thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => router.push(`/clients/${c.id}`)}>
                  <td><strong>{c.full_name}</strong></td>
                  <td className="small">{label(PARTY_TYPE, c.party_type)}</td>
                  <td>{c.phone}</td>
                  <td>{c.identity_verified ? <Badge tone="ok">Проверена</Badge> : <Badge tone="warn">Не проверена</Badge>}</td>
                  <td>{c.has_cabinet_access ? <Badge tone="ok">Есть доступ</Badge> : <Badge>Нет</Badge>}</td>
                  <td className="small">{formatDate(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
