"""Минимальный HTTP-клиент для интеграций (без сторонних библиотек). В тестах подменяется."""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TIMEOUT = 30


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def request_json(method: str, url: str, *, json_body: dict | None = None, form: dict | None = None,
                 headers: dict[str, str] | None = None, basic_auth: tuple[str, str] | None = None) -> Any:
    data = None
    hdrs = {"Accept": "application/json", **(headers or {})}
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode()
        hdrs["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    if basic_auth:
        hdrs["Authorization"] = "Basic " + base64.b64encode(":".join(basic_auth).encode()).decode()
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 — адреса только из настроек
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw[:500].decode(errors="replace")
        raise HttpError(f"HTTP {e.code}", e.code, body) from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise HttpError(str(e)) from e
