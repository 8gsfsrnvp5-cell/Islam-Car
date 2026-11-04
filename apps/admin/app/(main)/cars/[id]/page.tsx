"use client";

import { AVAILABILITY, CAR_STATUS, OWNERSHIP, type StaffCar, api, formatDateTime, formatRub } from "@islamic-car/shared";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { CarChecklist } from "@/components/CarChecklist";
import { CarForm } from "@/components/CarForm";
import { useCan } from "@/components/Shell";
import { Badge, Card, ErrorBox, Loading, Notice, PageHead, StatusBadge } from "@/components/ui";
import { CLIENT_SITE_URL, useAction, useApi } from "@/lib/useApi";

export default function CarPage() {
  const { id } = useParams<{ id: string }>();
  const canWrite = useCan("cars.write");
  const canCost = useCan("cars.cost");
  const { data: car, error, setData } = useApi<StaffCar>(`/api/admin/cars/${id}`);
  const action = useAction();
  const [saved, setSaved] = useState(false);
  const [formKey, setFormKey] = useState(0);

  if (!car) return error ? <ErrorBox error={error} /> : <Loading />;

  async function save(payload: Record<string, unknown>) {
    setSaved(false);
    const updated = await action.run(() => api<StaffCar>(`/api/admin/cars/${id}`, { method: "PATCH", json: payload }));
    if (updated) { setData(updated); setSaved(true); setFormKey((k) => k + 1); }
  }

  async function togglePublish() {
    const path = car!.is_published ? "unpublish" : "publish";
    const updated = await action.run(() => api<StaffCar>(`/api/admin/cars/${id}/${path}`, { method: "POST" }));
    if (updated) setData(updated);
  }

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    for (const file of files) {
      const body = new FormData();
      body.append("file", file);
      const updated = await action.run(() => api<StaffCar>(`/api/admin/cars/${id}/photos`, { method: "POST", body }));
      if (updated) setData(updated);
    }
    e.target.value = "";
  }

  async function removePhoto(photoId: string) {
    const updated = await action.run(() => api<StaffCar>(`/api/admin/cars/${id}/photos/${photoId}`, { method: "DELETE" }));
    if (updated) setData(updated);
  }

  const availability = car.status === "reserved" ? "reserved" : car.ownership_status === "owned" ? "in_stock" : "purchasing";

  return (
    <>
      <PageHead
        title={`${car.make} ${car.model}, ${car.year}`}
        subtitle={<><StatusBadge status={car.ownership_status} labels={OWNERSHIP} /> <StatusBadge status={car.status} labels={CAR_STATUS} /> · изменён {formatDateTime(car.updated_at)}</>}
        actions={
          <>
            {car.is_published ? <a className="btn" href={`${CLIENT_SITE_URL}/cars/${car.id}`} target="_blank" rel="noreferrer">Открыть в каталоге</a> : null}
            {canWrite && car.status !== "sold" ? (
              <button className={car.is_published ? "btn" : "btn btn-primary"} onClick={togglePublish} disabled={action.busy}>
                {car.is_published ? "Снять с публикации" : "Опубликовать в каталоге"}
              </button>
            ) : null}
            {car.status !== "sold" && car.ownership_status === "owned" ? <Link className="btn" href={`/contracts/new?car=${car.id}`}>Подготовить договор</Link> : null}
          </>
        }
      />
      <ErrorBox error={action.error} />
      {saved ? <Notice tone="ok">Изменения сохранены</Notice> : null}
      <div className="split">
        <Card title="Карточка">
          {canWrite ? <CarForm key={formKey} car={car} canCost={canCost} busy={action.busy} onSubmit={save} submitLabel="Сохранить изменения" />
            : <p className="muted">Недостаточно прав для изменения карточки.</p>}
        </Card>
        <div>
          <Card title="Каталог">
            {car.is_published ? (
              <>
                <p><Badge tone="ok">Опубликован</Badge></p>
                <p className="small">Покупатели видят статус: <strong>{AVAILABILITY[availability]}</strong></p>
              </>
            ) : <p className="small muted">Не опубликован. Для публикации нужен статус «В продаже» или «Забронирован», цена и VIN (для автомобиля в собственности).</p>}
            <p className="small">Цена в каталоге: <strong>{formatRub(car.sale_price_kopecks)}</strong></p>
            {car.ownership_status === "purchasing" ? (
              <Notice tone="warn">Автомобиль в процессе закупки: в каталоге он отмечен соответствующим образом, договор подписать нельзя до перехода права собственности.</Notice>
            ) : null}
          </Card>
          <CarChecklist carId={car.id} />
          <Card title="Фотографии" subtitle="JPEG, PNG или WebP до 10 МБ">
            <div className="photos">
              {car.photos.map((p) => (
                <figure key={p.id}>
                  <img src={p.url} alt="" />
                  {canWrite ? <button className="btn btn-sm btn-danger" onClick={() => removePhoto(p.id)}>Удалить</button> : null}
                </figure>
              ))}
            </div>
            {canWrite ? <input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={upload} style={{ marginTop: 12 }} /> : null}
          </Card>
        </div>
      </div>
    </>
  );
}
