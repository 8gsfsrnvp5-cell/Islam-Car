"use client";

import type { Photo } from "@islamic-car/shared";
import { useRef, useState } from "react";

export function Gallery({ photos, alt }: { photos: Photo[]; alt: string }) {
  const [i, setI] = useState(0);
  const touchX = useRef<number | null>(null);
  if (!photos.length) return <div className="gallery-main">Фотографии готовятся</div>;
  const go = (step: number) => setI((cur) => (cur + step + photos.length) % photos.length);
  const many = photos.length > 1;

  // На телефоне фото листаются пальцем
  const onTouchEnd = (e: React.TouchEvent) => {
    if (touchX.current === null) return;
    const dx = e.changedTouches[0].clientX - touchX.current;
    touchX.current = null;
    if (Math.abs(dx) > 40) go(dx < 0 ? 1 : -1);
  };

  return (
    <div>
      <div className="gallery-main" onTouchStart={(e) => { touchX.current = e.touches[0].clientX; }} onTouchEnd={onTouchEnd}>
        <img src={photos[i].url} alt={alt} />
        {many ? (
          <>
            <button className="gallery-nav prev" onClick={() => go(-1)} aria-label="Предыдущее фото">‹</button>
            <button className="gallery-nav next" onClick={() => go(1)} aria-label="Следующее фото">›</button>
            <span className="gallery-count">{i + 1} / {photos.length}</span>
          </>
        ) : null}
      </div>
      {many ? (
        <div className="gallery-thumbs">
          {photos.map((p, idx) => (
            <button key={p.id} className={idx === i ? "active" : ""} onClick={() => setI(idx)} aria-label={`Фото ${idx + 1}`}>
              <img src={p.url} alt="" />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
