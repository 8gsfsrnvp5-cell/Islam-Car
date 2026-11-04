"""Validate scan structure without rewriting signed source bytes."""
import io
import warnings

from fastapi import HTTPException
from PIL import Image
from pypdf import PdfReader


def validate_scan(content: bytes) -> tuple[str, str]:
    try:
        if content.startswith(b"%PDF-"):
            pdf = PdfReader(io.BytesIO(content), strict=True)
            if pdf.is_encrypted or not 1 <= len(pdf.pages) <= 500:
                raise ValueError("Encrypted, empty or oversized PDF")
            # Reject active content, attachments and automatic actions throughout the object graph.
            seen = set()
            def visit(obj, depth=0):
                if depth > 50 or len(seen) > 50000:
                    raise ValueError("PDF too complex")
                obj = obj.get_object() if hasattr(obj, "get_object") else obj
                if id(obj) in seen:
                    return
                seen.add(id(obj))
                if isinstance(obj, dict):
                    if set(obj) & {"/JS", "/JavaScript", "/OpenAction", "/AA", "/EmbeddedFiles", "/EF"}:
                        raise ValueError("Active PDF content")
                    if obj.get("/S") in ("/Launch", "/JavaScript", "/SubmitForm", "/ImportData", "/GoToR"):
                        raise ValueError("External PDF action")
                    for value in obj.values():
                        visit(value, depth + 1)
                elif isinstance(obj, list):
                    for value in obj:
                        visit(value, depth + 1)
            visit(pdf.trailer)
            return "application/pdf", ".pdf"
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as img:
                fmt = img.format
                if fmt not in ("JPEG", "PNG") or img.width * img.height > 25_000_000:
                    raise ValueError("Unsupported image")
                img.verify()
            with Image.open(io.BytesIO(content)) as img:
                img.load()
        return ("image/jpeg", ".jpg") if fmt == "JPEG" else ("image/png", ".png")
    except Exception as exc:
        raise HTTPException(415, "Нужен корректный PDF без активного содержимого либо изображение JPEG/PNG") from exc
