"""Фотографии автомобилей: очистка метаданных, главное фото, распознавание по фото. Claude API не вызывается."""

import io
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import ExifTags, Image
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditLog, Role
from app.services import assistant, car_recognition, files
from tests.conftest import staff_client
from tests.helpers import create_car


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key-not-real")


def phone_photo(width=300, height=200, orientation=6) -> bytes:
    """JPEG как с телефона: координаты съёмки, модель телефона и поворот в EXIF."""
    img = Image.new("RGB", (width, height), (200, 30, 30))
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = orientation
    exif[ExifTags.Base.Model] = "Test Phone"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (55.0, 45.0, 21.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def upload(admin, car_id: str, content: bytes, name="car.jpg"):
    return admin.post(f"/api/admin/cars/{car_id}/photos", files={"file": (name, content, "image/jpeg")})


def test_uploaded_photo_has_no_location_and_is_rotated(admin, public):
    original = phone_photo()
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(ExifTags.IFD.GPSInfo)  # координаты были
    car = create_car(admin)
    r = upload(admin, car["id"], original)
    assert r.status_code == 201, r.text
    photo = r.json()["photos"][0]
    stored = public.get(photo["url"].replace("/api/admin/", "/api/public/"))
    assert stored.status_code == 200 and stored.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(stored.content))
    assert img.format == "JPEG" and img.size == (200, 300)  # поворот применён к пикселям
    assert not img.getexif() and b"Exif" not in stored.content and b"Test Phone" not in stored.content

    # Большой PNG с прозрачностью уменьшается и становится JPEG без прозрачности
    big = io.BytesIO()
    Image.new("RGBA", (3000, 1000), (0, 0, 0, 0)).save(big, "PNG")
    r = admin.post(f"/api/admin/cars/{car['id']}/photos", files={"file": ("a.png", big.getvalue(), "image/png")})
    assert r.status_code == 201, r.text
    img = Image.open(io.BytesIO(admin.get(r.json()["photos"][1]["url"]).content))
    assert img.size == (2560, 853) and img.mode == "RGB" and img.getpixel((5, 5)) == (255, 255, 255)


def test_fake_and_oversized_photos_are_rejected(admin, monkeypatch):
    car = create_car(admin)
    assert upload(admin, car["id"], b"\xff\xd8\xff" + b"0" * 200).status_code == 415  # подпись JPEG, внутри мусор
    assert upload(admin, car["id"], b"%PDF-1.7 not a photo").status_code == 415
    monkeypatch.setattr(files, "MAX_PIXELS", 1000)
    assert upload(admin, car["id"], phone_photo()).status_code == 413
    assert admin.get(f"/api/admin/cars/{car['id']}").json()["photos"] == []


def test_main_photo_goes_first_in_catalog(admin, public):
    car = create_car(admin)
    upload(admin, car["id"], phone_photo(orientation=1))
    second = upload(admin, car["id"], phone_photo(width=100, height=100, orientation=1)).json()["photos"][1]
    r = admin.post(f"/api/admin/cars/{car['id']}/photos/{second['id']}/main")
    assert r.status_code == 200, r.text
    assert r.json()["photos"][0]["id"] == second["id"]
    assert public.get(f"/api/public/cars/{car['id']}").json()["photos"][0]["id"] == second["id"]
    viewer = staff_client("auditor1", Role.auditor)
    assert viewer.post(f"/api/admin/cars/{car['id']}/photos/{second['id']}/main").status_code == 403


def enable(admin):
    r = admin.put("/api/admin/cars/recognition/settings", json={"enabled": True, "confirm_data_scope": True})
    assert r.status_code == 200, r.text
    return r.json()


def recognize(client, content: bytes):
    return client.post("/api/admin/cars/recognize", files={"file": ("car.jpg", content, "image/jpeg")})


def test_recognition_is_off_until_key_and_owner(admin, api_key, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    st = admin.get("/api/admin/cars/recognition").json()
    assert not st["enabled"] and "ANTHROPIC_API_KEY" in st["reason"]
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key-not-real")
    assert "Владелец" in admin.get("/api/admin/cars/recognition").json()["reason"]
    assert recognize(admin, phone_photo()).status_code == 409
    r = admin.put("/api/admin/cars/recognition/settings", json={"enabled": True})
    assert r.status_code == 422  # без подтверждения состава данных
    manager = staff_client("manager1", Role.manager)
    assert manager.put("/api/admin/cars/recognition/settings",
                       json={"enabled": True, "confirm_data_scope": True}).status_code == 403
    assert enable(admin)["enabled"]
    # Включение помощника по нормам не сбрасывает распознавание
    admin.put("/api/admin/assistant/settings", json={"enabled": True, "confirm_data_scope": True})
    assert admin.get("/api/admin/cars/recognition").json()["enabled"]
    assert recognize(staff_client("auditor1", Role.auditor), phone_photo()).status_code == 403


def test_recognition_result_is_checked_before_reaching_form(admin, api_key, monkeypatch):
    enable(admin)
    sent = {}

    def fake_call(jpeg: bytes) -> dict:
        sent["jpeg"] = jpeg
        return {"is_car": True, "make": " Toyota ", "model": "Camry", "generation": "XV70", "body_type": "седан",
                "color": "белый", "year_from": 2021, "year_to": 2017, "visible_features": "литые диски",
                "vin": "XTA2109901234567I", "plate_visible": True, "people_visible": False,
                "documents_visible": False, "confidence": "high", "notes": "узнаваемая решётка радиатора"}

    monkeypatch.setattr(car_recognition, "call_model", fake_call)
    r = recognize(admin, phone_photo(width=4000, height=3000))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["fields"] == {"make": "Toyota", "model": "Camry", "body_type": "седан", "color": "белый"}
    assert data["year_from"] == 0 and data["year_to"] == 0  # годы перепутаны — не показываем
    assert any("госномер" in w for w in data["warnings"]) and any("VIN" in w for w in data["warnings"])
    assert data["generation"] == "XV70" and data["confidence_label"] == "высокая" and data["disclaimer"]
    img = Image.open(io.BytesIO(sent["jpeg"]))
    assert max(img.size) == 1280 and not img.getexif() and b"Test Phone" not in sent["jpeg"]
    with SessionLocal() as db:
        entry = db.scalar(select(AuditLog).where(AuditLog.action == "car.recognized"))
        assert entry.data["make"] == "Toyota" and "jpeg" not in json.dumps(entry.data)

    monkeypatch.setattr(car_recognition, "call_model", lambda jpeg: {
        **fake_call(jpeg), "is_car": False, "vin": "XTA21099012345678", "confidence": "low"})
    data = recognize(admin, phone_photo()).json()
    assert data["fields"] == {} and not data["is_car"] and "не найден автомобиль" in data["warnings"][0]


def test_recognition_request_shape_and_refusal(api_key, monkeypatch):
    payload = {"is_car": False}
    captured = {}

    class Messages:
        def __init__(self, response):
            self.response = response

        def create(self, **kwargs):
            captured.update(kwargs)
            return self.response

    ok = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))])
    monkeypatch.setattr(assistant, "client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=Messages(ok))))
    assert car_recognition.call_model(b"\xff\xd8\xff-jpeg") == payload
    image, text = captured["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg" and text["type"] == "text"
    assert captured["output_config"]["format"]["schema"] == car_recognition.SCHEMA
    assert captured["model"] == "claude-opus-5-5" and "цену" in captured["system"][0]["text"].lower()

    refusal = SimpleNamespace(stop_reason="refusal", content=[])
    monkeypatch.setattr(assistant, "client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=Messages(refusal))))
    with pytest.raises(HTTPException) as e:
        car_recognition.call_model(b"\xff\xd8\xff-jpeg")
    assert e.value.status_code == 422
