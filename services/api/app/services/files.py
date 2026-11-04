"""Хранение загруженных файлов вне базы и вне git."""

import io
import uuid
import warnings
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings

# Проверяем реальные сигнатуры файлов, а не только заявленный тип
SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
# Фото пересохраняется в JPEG: метаданные (координаты съёмки, модель телефона, дата) не переносятся,
# поворот из EXIF применяется к пикселям, слишком большие снимки уменьшаются
MAX_SIDE = 2560
# Защита от «бомб» — файлов с огромным разрешением при небольшом размере
MAX_PIXELS = 60_000_000
NOT_A_PHOTO = "Допустимы только фотографии JPEG, PNG или WebP"


def photos_dir() -> Path:
    d = get_settings().storage_dir / "car-photos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def photo_path(file_name: str) -> Path:
    path = (photos_dir() / file_name).resolve()
    if path.parent != photos_dir().resolve() or not path.is_file():
        raise HTTPException(404, "Файл не найден")
    return path


def detect_type(content: bytes) -> str | None:
    content_type = next((ct for ct, sigs in SIGNATURES.items()
                         if any(content.startswith(s) for s in sigs)), None)
    if content_type == "image/webp" and content[8:12] != b"WEBP":
        return None
    return content_type


async def read_photo(upload: UploadFile) -> bytes:
    limit = get_settings().max_photo_bytes
    content = await upload.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"Файл больше {limit // (1024 * 1024)} МБ")
    if detect_type(content) is None:
        raise HTTPException(415, NOT_A_PHOTO)
    return content


def normalize_image(content: bytes, max_side: int = MAX_SIDE, quality: int = 85) -> bytes:
    """Пересохраняет фото в JPEG без метаданных. Повреждённый или не графический файл — ошибка 415."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(content))
            if img.width * img.height > MAX_PIXELS:
                raise HTTPException(413, "Слишком большое разрешение фотографии")
            img.load()
            img = ImageOps.exif_transpose(img)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise HTTPException(415, "Файл повреждён или не является фотографией") from None
    icc = img.info.get("icc_profile")  # цветовой профиль сохраняем, он не содержит сведений о съёмке
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, (255, 255, 255))
        img.paste(rgba, mask=rgba.getchannel("A"))
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True, icc_profile=icc)
    return out.getvalue()


async def save_photo(upload: UploadFile) -> tuple[str, str]:
    data = normalize_image(await read_photo(upload))
    name = f"{uuid.uuid4().hex}.jpg"
    (photos_dir() / name).write_bytes(data)
    return name, "image/jpeg"
