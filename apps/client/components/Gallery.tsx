"use client";

import type { Photo } from "@islamic-car/shared";
import { useState } from "react";

export function Gallery({ photos, alt }: { photos: Photo[]; alt: string }) {
  const [i, setI] = useState(0);
  if (!photos.length) return <div className="gallery-main">Фотографии готовятся</div>;
  return (
    <div>
      <div className="gallery-main"><img src={photos[i].url} alt={alt} /></div>
      {photos.length > 1 ? (
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
