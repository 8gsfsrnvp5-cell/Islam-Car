"""Версия 4: помощник по библиотекам знаний. Claude API в тестах не вызывается — вызов подменяется."""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.db import SessionLocal
from app.knowledge.service import load_records
from app.models import AuditLog, Role
from app.services import assistant
from tests.conftest import staff_client
from tests.helpers import create_verified_client, setup_company, signed_deal


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key-not-real")


def enable(admin):
    r = admin.put("/api/admin/assistant/settings", json={"enabled": True, "confirm_data_scope": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_assistant_is_off_until_key_and_owner(admin, api_key, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    st = admin.get("/api/admin/assistant").json()
    assert st["enabled"] is False and "ANTHROPIC_API_KEY" in st["reason"]
    assert admin.post("/api/admin/assistant/ask", json={"question": "Что такое мурабаха?"}).status_code == 409

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key-not-real")
    assert "Владелец" in admin.get("/api/admin/assistant").json()["reason"]
    r = admin.put("/api/admin/assistant/settings", json={"enabled": True})
    assert r.status_code == 422  # без подтверждения состава передаваемых данных
    manager = staff_client("manager1", Role.manager)
    assert manager.put("/api/admin/assistant/settings", json={"enabled": True, "confirm_data_scope": True}) \
        .status_code == 403
    assert enable(admin)["enabled"] is True
    assert staff_client("auditor1", Role.auditor).post("/api/admin/assistant/ask",
                                                       json={"question": "Что такое мурабаха?"}).status_code == 403


def test_question_is_redacted_and_answer_checked_by_system(admin, api_key, monkeypatch):
    _, client, contract = signed_deal(admin)
    enable(admin)
    legal = next(r for r in load_records() if r.library == "legal")
    sent = {}

    def fake_call(system_records: str, user_text: str) -> dict:
        sent["records"], sent["user"] = system_records, user_text
        return {"answer": f"Срок — 45 дней [{legal.code}].", "cited_codes": [legal.code, "legal.made.up"],
                "enough_basis": True, "specialists": []}

    monkeypatch.setattr(assistant, "call_model", fake_call)
    question = (f"Покупатель Иванов (тел. +7 900 111-22-33, паспорт 4510 123456, ivanov@mail.test) по договору "
                f"{contract['number']} просит отсрочку. Можно ли продлить график?")
    preview = admin.post("/api/admin/assistant/preview", json={"question": question}).json()
    r = admin.post("/api/admin/assistant/ask", json={"question": question, "reviewed_question": preview["question"]})
    assert r.status_code == 200, r.text
    body = r.json()

    for secret in ("Иванов", "900 111-22-33", "4510 123456", "ivanov@mail.test", contract["number"]):
        assert secret not in sent["user"] and secret not in body["question_sent"]
    assert {"[ФИО]", "[телефон]", "[паспорт]", "[email]", "[номер договора]"} <= set(body["removed"])
    assert "Иванов" not in sent["records"] and client["phone"] not in sent["records"]  # в запросе только библиотеки

    # Надёжность определяет система: запись без заключения юриста → «Требуется проверка»
    assert body["verdict"].startswith("Требуется проверка юриста")
    assert [s["code"] for s in body["sources"]] == [legal.code] and body["sources"][0]["reliable"] is False
    assert any("45" in w for w in body["warnings"])          # числа нет в записи
    assert any("legal.made.up" in w for w in body["warnings"])
    assert "Не является заключением" in body["disclaimer"]

    with SessionLocal() as db:
        logged = [a.data for a in db.query(AuditLog).filter(AuditLog.action == "assistant.asked")]
    assert logged and "900 111-22-33" not in json.dumps(logged, ensure_ascii=False)


def test_redaction_handles_other_identifiers(admin):
    setup_company(admin)
    create_verified_client(admin, name="Петров Пётр Петрович")
    with SessionLocal() as db:
        clean, removed = assistant.redact(db, "Петров, ИНН 7700000000, счёт 40817810000000000001, VIN "
                                              "XTA21099012345678, А123ВС77, СНИЛС 112-233-445 95, родился 01.05.1990")
    for secret in ("Петров", "7700000000", "40817810000000000001", "XTA21099012345678", "А123ВС77", "112-233-445",
                   "01.05.1990"):
        assert secret not in clean
    assert "[ФИО]" in removed


class FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(monkeypatch, response) -> FakeMessages:
    messages = FakeMessages(response)
    monkeypatch.setattr(assistant, "client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    return messages


def test_call_model_request_shape_and_stop_reasons(api_key, monkeypatch):
    payload = {"answer": "Нет основания", "cited_codes": [], "enough_basis": False, "specialists": ["legal"]}
    ok = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))])
    messages = fake_client(monkeypatch, ok)
    assert assistant.call_model("[]", "вопрос") == payload
    kw = messages.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["output_config"]["effort"] == "medium"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"} and "thinking" not in kw

    fake_client(monkeypatch, SimpleNamespace(stop_reason="refusal", content=[]))
    with pytest.raises(HTTPException) as e:
        assistant.call_model("[]", "вопрос")
    assert e.value.status_code == 422

    fake_client(monkeypatch, SimpleNamespace(stop_reason="max_tokens", content=[]))
    with pytest.raises(HTTPException) as e:
        assistant.call_model("[]", "вопрос")
    assert e.value.status_code == 502
