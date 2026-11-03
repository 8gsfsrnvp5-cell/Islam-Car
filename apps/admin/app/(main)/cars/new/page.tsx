"use client";

import { type StaffCar, api, errorText } from "@islamic-car/shared";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  PhotoPicker, type Recognition, RecognitionOff, RecognitionResult, recognizePhoto, useRecognition, yearHint,
} from "@/components/CarPhotoTools";
import { CarForm, type Prefill } from "@/components/CarForm";
import { useCan } from "@/components/Shell";
import { Card, ErrorBox, Notice, PageHead } from "@/components/ui";
import { useAction } from "@/lib/useApi";

type Draft = { key: string; file: File; url: string };

export default function NewCarPage() {
  const router = useRouter();
  const canCost = useCan("cars.cost");
  const action = useAction();
  const recognition = useRecognition();
  const [photos, setPhotos] = useState<Draft[]>([]);
  const [result, setResult] = useState<Recognition | null>(null);
  const [recognizing, setRecognizing] = useState<string | null>(null);
  const [recError, setRecError] = useState<string | null>(null);
  const [prefill, setPrefill] = useState<Prefill | null>(null);
  const [publishNow, setPublishNow] = useState(true);
  const [step, setStep] = useState<string | null>(null);
  const urls = useRef<string[]>([]);

  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), []);
  const enabled = Boolean(recognition.data?.enabled);

  async function recognize(d: Draft) {
    setRecognizing(d.key);
    setRecError(null);
    try {
      const r = await recognizePhoto(d.file);
      setResult(r);
      setPrefill({ values: r.fields as Record<string, string>, nonce: Date.now() });
    } catch (e) {
      setRecError(errorText(e));
    } finally {
      setRecognizing(null);
    }
  }

  function add(files: File[]) {
    const drafts = files.map((file) => {
      const url = URL.createObjectURL(file);
      urls.current.push(url);
      return { key: `${Date.now()}-${Math.random()}`, file, url };
    });
    setPhotos((prev) => [...prev, ...drafts]);
    // Первое фото распознаётся сразу; остальные — по кнопке
    if (enabled && !result && !recognizing && drafts[0]) void recognize(drafts[0]);
  }

  const remove = (key: string) => setPhotos((prev) => prev.filter((p) => p.key !== key));
  const makeMain = (key: string) => setPhotos((prev) => [...prev.filter((p) => p.key === key), ...prev.filter((p) => p.key !== key)]);

  async function create(payload: Record<string, unknown>) {
    if (publishNow && payload.status === "draft") payload.status = "available";
    setStep("Сохраняем карточку…");
    const car = await action.run(() => api<StaffCar>("/api/admin/cars", { method: "POST", json: payload }));
    if (!car) { setStep(null); return; }
    // Карточка создана: дальше ошибки не возвращают на эту страницу, иначе повторное сохранение создаст дубль
    const problems: string[] = [];
    for (const [i, p] of photos.entries()) {
      setStep(`Загружаем фото ${i + 1} из ${photos.length}…`);
      const body = new FormData();
      body.append("file", p.file);
      try {
        await api<StaffCar>(`/api/admin/cars/${car.id}/photos`, { method: "POST", body });
      } catch (e) {
        problems.push(`Фото ${i + 1}: ${errorText(e)}`);
      }
    }
    if (publishNow) {
      setStep("Публикуем в каталоге…");
      try {
        await api<StaffCar>(`/api/admin/cars/${car.id}/publish`, { method: "POST" });
      } catch (e) {
        problems.push(errorText(e));
      }
    }
    const q = new URLSearchParams({ created: "1" });
    if (problems.length) q.set("problems", problems.join("\n"));
    router.push(`/cars/${car.id}?${q}`);
  }

  return (
    <>
      <PageHead title="Новый автомобиль" subtitle="Сфотографируйте машину — характеристики подставятся в карточку. Цену указываете вы." />
      <Card title="Фотографии" subtitle="Первое фото — главное в каталоге. Метаданные снимков (место съёмки, модель телефона) удаляются при загрузке">
        <PhotoPicker onFiles={add} disabled={action.busy} />
        {photos.length ? (
          <div className="photos" style={{ marginTop: 12 }}>
            {photos.map((p, i) => (
              <figure key={p.key}>
                <img src={p.url} alt="" />
                {i === 0 ? <figcaption>Главное</figcaption> : null}
                <div className="actions">
                  {i > 0 ? <button type="button" className="btn btn-sm" onClick={() => makeMain(p.key)}>Главное</button> : null}
                  {enabled ? (
                    <button type="button" className="btn btn-sm" onClick={() => recognize(p)} disabled={Boolean(recognizing)}>
                      {recognizing === p.key ? "Распознаём…" : "Распознать"}
                    </button>
                  ) : null}
                  <button type="button" className="btn btn-sm btn-danger" onClick={() => remove(p.key)}>Убрать</button>
                </div>
              </figure>
            ))}
          </div>
        ) : null}
        {recognition.data && !enabled ? <RecognitionOff status={recognition.data} /> : null}
        {recognizing ? <Notice tone="info">Распознаём автомобиль по фото — обычно это занимает несколько секунд…</Notice> : null}
        {recError ? <Notice tone="danger">{recError}</Notice> : null}
        {result ? <RecognitionResult result={result} /> : null}
      </Card>
      <ErrorBox error={action.error} />
      {step ? <Notice tone="info">{step}</Notice> : null}
      <Card>
        <label className="publish-now">
          <input type="checkbox" checked={publishNow} onChange={(e) => setPublishNow(e.target.checked)} />{" "}
          Сразу опубликовать в каталоге для клиентов (статус станет «В продаже»)
        </label>
        <CarForm canCost={canCost} busy={action.busy || Boolean(step)} onSubmit={create} submitLabel="Сохранить карточку"
                 prefill={prefill} hints={{ year: yearHint(result) }} />
      </Card>
    </>
  );
}
