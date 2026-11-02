"use client";

import { type StaffCar, api } from "@islamic-car/shared";
import { useRouter } from "next/navigation";

import { CarForm } from "@/components/CarForm";
import { useCan } from "@/components/Shell";
import { Card, ErrorBox, PageHead } from "@/components/ui";
import { useAction } from "@/lib/useApi";

export default function NewCarPage() {
  const router = useRouter();
  const canCost = useCan("cars.cost");
  const action = useAction();

  async function create(payload: Record<string, unknown>) {
    const car = await action.run(() => api<StaffCar>("/api/admin/cars", { method: "POST", json: payload }));
    if (car) router.push(`/cars/${car.id}`);
  }

  return (
    <>
      <PageHead title="Новый автомобиль" subtitle="После сохранения можно загрузить фотографии и опубликовать карточку в каталоге" />
      <ErrorBox error={action.error} />
      <Card><CarForm canCost={canCost} busy={action.busy} onSubmit={create} submitLabel="Сохранить карточку" /></Card>
    </>
  );
}
