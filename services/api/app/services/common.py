import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.config import get_settings

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # без I, O, Q


def today() -> date:
    """Сегодня по часовому поясу компании — от этого зависит просрочка."""
    return datetime.now(ZoneInfo(get_settings().company_timezone)).date()


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "3489":
        raise HTTPException(422, "Укажите российский номер телефона, например +7 900 123-45-67")
    return "+7" + digits


def normalize_vin(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    vin = raw.strip().upper()
    if not VIN_RE.match(vin):
        raise HTTPException(422, "VIN должен состоять из 17 символов (латинские буквы без I, O, Q и цифры)")
    return vin


def mask_tail(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible:
        return "•" * len(value)
    return "•" * (len(value) - visible) + value[-visible:]


def mask_phone(phone: str) -> str:
    if len(phone) < 6:
        return mask_tail(phone, 2)
    return phone[:2] + " ••• •••-" + phone[-4:-2] + "-" + phone[-2:]
