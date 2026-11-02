"""Хранение загруженных файлов вне базы и вне git."""

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import get_settings

# Проверяем реальные сигнатуры файлов, а не только заявленный тип
SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def photos_dir() -> Path:
    d = get_settings().storage_dir / "car-photos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def photo_path(file_name: str) -> Path:
    path = (photos_dir() / file_name).resolve()
    if path.parent != photos_dir().resolve() or not path.is_file():
        raise HTTPException(404, "Файл не найден")
    return path


async def save_photo(upload: UploadFile) -> tuple[str, str]:
    limit = get_settings().max_photo_bytes
    content = await upload.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"Файл больше {limit // (1024 * 1024)} МБ")
    content_type = next((ct for ct, sigs in SIGNATURES.items()
                         if any(content.startswith(s) for s in sigs)), None)
    if content_type == "image/webp" and content[8:12] != b"WEBP":
        content_type = None
    if content_type is None:
        raise HTTPException(415, "Допустимы только фотографии JPEG, PNG или WebP")
    name = f"{uuid.uuid4().hex}{EXTENSIONS[content_type]}"
    (photos_dir() / name).write_bytes(content)
    return name, content_type
