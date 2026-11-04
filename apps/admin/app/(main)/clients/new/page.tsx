"use client";

import { api } from "@islamic-car/shared";
import { useRouter } from "next/navigation";

import { type ClientData, ClientForm } from "@/components/ClientForm";
import { Card, ErrorBox, Notice, PageHead } from "@/components/ui";
import { useAction } from "@/lib/useApi";

export default function NewClientPage() {
  const router = useRouter();
  const action = useAction();

  async function create(payload: Record<string, unknown>) {
    const c = await action.run(() => api<ClientData>("/api/admin/clients", { method: "POST", json: payload }));
    if (c) router.push(`/clients/${c.id}`);
  }

  return (
    <>
      <PageHead title="Новый клиент" />
      <Notice tone="info">
        Вносите только данные, которые нужны для договора, и только после получения согласия клиента на обработку персональных данных.
        Личность подтверждается отдельно — по оригиналу документа.
      </Notice>
      <ErrorBox error={action.error} />
      <Card><ClientForm busy={action.busy} onSubmit={create} submitLabel="Создать клиента" /></Card>
    </>
  );
}
