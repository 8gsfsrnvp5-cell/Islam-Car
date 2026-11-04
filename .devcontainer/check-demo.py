"""Проверка демо-стенда после start-demo.sh: сайт и админка открываются, чужой сайт не может войти,
владелец входит, фото загружается и появляется на сайте без метаданных, проверочное фото удаляется.

    python3 .devcontainer/check-demo.py

Нужен только Python 3 (стандартная библиотека). Адреса берутся из .env, вход — из .demo/owner.env;
пароль не печатается. Демо-данные не меняются: проверочное фото удаляется в конце.
"""

import http.cookiejar
import json
import shlex
import struct
import sys
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = b"Demo Check Phone"


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = (shlex.split(value) or [""])[0]
    return values


def photo_with_metadata() -> bytes:
    """PNG 64×40, в метаданных (EXIF) — «модель телефона». После загрузки её не должно быть."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    width, height = 64, 40
    pixels = b"".join(b"\x00" + bytes((40, 92, 69)) * width for _ in range(height))
    model = MARK + b"\x00"
    exif = (b"MM\x00\x2a" + struct.pack(">I", 8) + struct.pack(">H", 1)
            + struct.pack(">HHII", 0x0110, 2, len(model), 26) + struct.pack(">I", 0) + model)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"eXIf", exif) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


env = read_env(ROOT / ".env")
owner = read_env(ROOT / ".demo" / "owner.env")
client = env["PUBLIC_CLIENT_URL"]
admin = [o for o in env["ALLOWED_ORIGINS"].split(",") if o != client][0]

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
failures = 0


def call(base, method, path, body=None, headers=None, origin=None):
    h = {"User-Agent": "islamcar-demo-check", **(headers or {})}
    if method != "GET":
        h["Origin"] = origin or base
    req = urllib.request.Request(base + path, data=body, method=method, headers=h)
    try:
        with opener.open(req, timeout=60) as r:
            return r.status, r.read(), r.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("content-type", "")


def check(title, ok, detail=""):
    global failures
    print(("ОК    " if ok else "ОШИБКА") + f"  {title}" + (f" ({detail})" if detail else ""))
    if not ok:
        failures += 1
    return ok


s, _, _ = call(client, "GET", "/")
check("сайт для покупателей открывается", s == 200, str(s))
s, _, _ = call(admin, "GET", "/login")
check("админка открывается", s == 200, str(s))

login = json.dumps({"login": owner["OWNER_LOGIN"], "password": owner["OWNER_PASSWORD"]}).encode()
json_header = {"Content-Type": "application/json"}
s, _, _ = call(admin, "POST", "/api/auth/admin/login", login, json_header, origin="https://evil.example")
check("запрос с чужого сайта отклонён", s == 403, str(s))
s, _, _ = call(admin, "POST", "/api/auth/admin/login", login, json_header)
if not check("владелец входит в админку", s == 200, str(s)):
    sys.exit(1)

s, raw, _ = call(admin, "GET", "/api/admin/cars")
car = next((c for c in json.loads(raw) if c["is_published"]), None) if s == 200 else None
if not check("в каталоге есть опубликованный автомобиль", car is not None, str(s)):
    sys.exit(1)

boundary = uuid.uuid4().hex
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="check.png"\r\n'
        "Content-Type: image/png\r\n\r\n").encode() + photo_with_metadata() + f"\r\n--{boundary}--\r\n".encode()
s, raw, _ = call(admin, "POST", f"/api/admin/cars/{car['id']}/photos", body,
                 {"Content-Type": f"multipart/form-data; boundary={boundary}"})
if not check("фото загружается в админке", s == 201, str(s)):
    sys.exit(1)
photo = json.loads(raw)["photos"][-1]["id"]
try:
    s, raw, _ = call(client, "GET", f"/api/public/cars/{car['id']}")
    check("фото есть в каталоге сайта", s == 200 and photo in raw.decode(), str(s))
    s, raw, _ = call(client, "GET", f"/cars/{car['id']}")
    check("фото есть на странице автомобиля", s == 200 and photo in raw.decode("utf-8", "replace"), str(s))
    s, img, ct = call(client, "GET", f"/api/public/cars/{car['id']}/photos/{photo}")
    check("картинка открывается на сайте", s == 200 and img.startswith(b"\xff\xd8\xff"), f"{s}, {ct}")
    check("метаданные из фото удалены", MARK not in img)
finally:
    s, _, _ = call(admin, "DELETE", f"/api/admin/cars/{car['id']}/photos/{photo}")
    check("проверочное фото удалено", s in (200, 204), str(s))
    call(admin, "POST", "/api/auth/admin/logout")

print("\nВсё работает." if not failures else f"\nОшибок: {failures}")
sys.exit(1 if failures else 0)
