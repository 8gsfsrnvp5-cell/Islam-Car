"use client";

import { api } from "@islamic-car/shared";
import Link from "next/link";
import { useRef } from "react";

import { Badge, Notice } from "@/components/ui";
import { useApi } from "@/lib/useApi";

export type RecognitionStatus = {
  enabled: boolean; configured: boolean; model: string; reason: string; changed_at: string | null;
  can_manage: boolean; data_scope: string; disclaimer: string;
};

export type Recognition = {
  is_car: boolean; fields: Partial<Record<"make" | "model" | "body_type" | "color" | "vin", string>>;
  generation: string; year_from: number; year_to: number; visible_features: string;
  confidence: "high" | "medium" | "low"; confidence_label: string; notes: string; warnings: string[];
  disclaimer: string; model: string;
};

export const PHOTO_TYPES = "image/jpeg,image/png,image/webp";

export function yearHint(r: Recognition | null): string | undefined {
  if (!r?.year_from) return undefined;
  return `По фото: поколение выпускалось ${r.year_from}–${r.year_to || "н. в."}. Точный год — по ПТС или СТС.`;
}

export function useRecognition() {
  return useApi<RecognitionStatus>("/api/admin/cars/recognition");
}

export function recognizePhoto(file: Blob): Promise<Recognition> {
  const body = new FormData();
  body.append("file", file, "photo.jpg");
  return api<Recognition>("/api/admin/cars/recognize", { method: "POST", body });
}

/** Две кнопки: снять камерой телефона или выбрать готовые фото. На компьютере обе открывают выбор файлов. */
export function PhotoPicker({ onFiles, disabled }: { onFiles: (files: File[]) => void; disabled?: boolean }) {
  const camera = useRef<HTMLInputElement>(null);
  const gallery = useRef<HTMLInputElement>(null);
  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length) onFiles(files);
  };
  return (
    <div className="actions photo-picker">
      <button type="button" className="btn btn-primary" onClick={() => camera.current?.click()} disabled={disabled}>
        Сфотографировать
      </button>
      <button type="button" className="btn" onClick={() => gallery.current?.click()} disabled={disabled}>
        Выбрать фото
      </button>
      <input ref={camera} type="file" accept={PHOTO_TYPES} capture="environment" hidden onChange={pick} />
      <input ref={gallery} type="file" accept={PHOTO_TYPES} multiple hidden onChange={pick} />
    </div>
  );
}

export function RecognitionOff({ status }: { status: RecognitionStatus }) {
  return (
    <Notice tone="info">
      Распознавание по фото выключено: {status.reason.toLowerCase()}.{" "}
      {status.can_manage && status.configured ? <Link href="/settings">Включить в настройках</Link>
        : !status.configured ? "Для него нужен ключ Claude API на сервере." : "Включает владелец."}{" "}
      Фотографии загружаются и без него.
    </Notice>
  );
}

export function RecognitionResult({ result, onApply, applyLabel }: {
  result: Recognition; onApply?: () => void; applyLabel?: string;
}) {
  const f = result.fields;
  const years = result.year_from ? `${result.year_from}–${result.year_to || "н. в."}` : "";
  const tone = result.confidence === "high" ? "ok" : result.confidence === "medium" ? "info" : "warn";
  return (
    <div className="recognition">
      {result.is_car ? (
        <>
          <div className="recognition-title">
            <strong>{[f.make, f.model, result.generation].filter(Boolean).join(" ") || "Модель не определена"}</strong>
            <Badge tone={tone}>уверенность: {result.confidence_label}</Badge>
          </div>
          <p className="small">
            {[f.body_type, f.color, years ? `поколение выпускалось ${years}` : "", f.vin ? `VIN ${f.vin}` : ""]
              .filter(Boolean).join(" · ")}
          </p>
          {result.visible_features ? <p className="small muted">На фото: {result.visible_features}</p> : null}
        </>
      ) : null}
      {result.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
      <p className="small muted">{result.disclaimer}</p>
      {onApply && Object.keys(f).length ? (
        <button type="button" className="btn btn-sm" onClick={onApply}>{applyLabel ?? "Подставить в карточку"}</button>
      ) : null}
    </div>
  );
}
