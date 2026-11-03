"use client";

import { AVAILABILITY, CAR_STATUS, OWNERSHIP, type StaffCar, api, errorText, formatDateTime, formatRub } from "@islamic-car/shared";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { CarChecklist } from "@/components/CarChecklist";
import {
  PhotoPicker, type Recognition, RecognitionOff, RecognitionResult, recognizePhoto, useRecognition, yearHint,
} from "@/components/CarPhotoTools";
import { CarForm, type Prefill } from "@/components/CarForm";
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
  const recognition = useRecognition();
  const [result, setResult] = useState<Recognition | null>(null);
  const [recognizing, setRecognizing] = useState<string | null>(null);
  const [recError, setRecError] = useState<string | null>(null);
  const [prefill, setPrefill] = useState<Prefill | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [created, setCreated] = useState<{ problems: string[] } | null>(null);

  // Итог создания карточки со страницы «Новый автомобиль»; адрес очищаем, чтобы сообщение не повторялось
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (!q.get("created")) return;
    setCreated({ problems: (q.get("problems") ?? "").split("\n").filter(Boolean) });
    window.history.replaceState(null, "", window.location.pathname);
  }, []);

  if (!car) return error ? <ErrorBox error={error} /> : <Loading />;

  async function save(payload: Record<string, unknown>) {
    setSaved(false);
    const updated = await action.run(() => api<StaffCar>(`/api/admin/cars/${id}`, { method: "PATCH", json: payload }));
    if (updated) { setData(updated); setSaved(true); setPrefill(null); setFormKey((k) => k + 1); }
  }

  async function togglePublish() {
    const path = car!.is_published ? "unpublish" : "publish";
    const updated = await action.run(() => api<StaffCar>(`/api/admin/cars/${id}/${path}`, { method: "POST" }));
    if (updated) setData(updated);
  }

  async function upload(files: File[]) {
    for (const [i, file] of files.entries()) {
      setUploading(`Загружаем фото ${i + 1} из ${files.length}…`);
      const body = new FormData();
      body.append("file", file);
      const updated = await action.run(() => api<StaffCar>(`/api/admin/cars/${id}/photos`, { method: "POST", body }));
      if (updated) setData(updated);
    }
    setUploading(null);
  }

  async function removePhoto(photoId: string) {
    const updated = await action.run(() => api<StaffCar>(`/api/admin/cars/${id}/photos/${photoId}`, { method: "DELETE" }));
    if (updated) setData(updated);
  }

  async function makeMain(photoId: string) {
    const updated = await action.run(() => api<StaffCar>(`/api/admin/cars/${id}/photos/${photoId}/main`, { method: "POST" }));
    if (updated) setData(updated);
  }

  async function recognize(photo: { id: string; url: string }) {
    setRecognizing(photo.id);
    setRecError(null);
    try {
      const blob = await (await fetch(photo.url, { credentials: "same-origin" })).blob();
      setResult(await recognizePhoto(blob));
    } catch (e) {
      setRecError(errorText(e));
    } finally {
      setRecognizing(null);
    }
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
      {created ? (
        created.problems.length ? (
          <Notice tone="warn" title="Карточка создана, но не всё получилось">
            {created.problems.map((p) => <div key={p}>{p}</div>)}
          </Notice>
        ) : <Notice tone="ok">Карточка создана{car.is_published ? " и опубликована в каталоге" : ""}</Notice>
      ) : null}
      <ErrorBox error={action.error} />
      {saved ? <Notice tone="ok">Изменения сохранены</Notice> : null}
      <div className="split">
        <Card title="Карточка">
          {canWrite ? <CarForm key={formKey} car={car} canCost={canCost} busy={action.busy} onSubmit={save} submitLabel="Сохранить изменения"
                               prefill={prefill} hints={{ year: yearHint(result) }} />
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
          <Card title="Фотографии" subtitle="JPEG, PNG или WebP до 10 МБ. Первое фото — главное в каталоге. Место съёмки и модель телефона из снимков удаляются">
            {canWrite ? <PhotoPicker onFiles={upload} disabled={action.busy || Boolean(uploading)} /> : null}
            {uploading ? <Notice tone="info">{uploading}</Notice> : null}
            <div className="photos" style={{ marginTop: 12 }}>
              {car.photos.map((p, i) => (
                <figure key={p.id}>
                  <img src={p.url} alt="" />
                  {i === 0 ? <figcaption>Главное</figcaption> : null}
                  {canWrite ? (
                    <div className="actions">
                      {i > 0 ? <button className="btn btn-sm" onClick={() => makeMain(p.id)} disabled={action.busy}>Главное</button> : null}
                      {recognition.data?.enabled ? (
                        <button className="btn btn-sm" onClick={() => recognize(p)} disabled={Boolean(recognizing)}>
                          {recognizing === p.id ? "Распознаём…" : "Распознать"}
                        </button>
                      ) : null}
                      <button className="btn btn-sm btn-danger" onClick={() => removePhoto(p.id)}>Удалить</button>
                    </div>
                  ) : null}
                </figure>
              ))}
            </div>
            {canWrite && recognition.data && !recognition.data.enabled ? <RecognitionOff status={recognition.data} /> : null}
            {recError ? <Notice tone="danger">{recError}</Notice> : null}
            {result ? (
              <RecognitionResult result={result} applyLabel="Подставить в пустые поля карточки"
                                 onApply={canWrite ? () => setPrefill({ values: result.fields as Record<string, string>, nonce: Date.now() }) : undefined} />
            ) : null}
          </Card>
        </div>
      </div>
    </>
  );
}
