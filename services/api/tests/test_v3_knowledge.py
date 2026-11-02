"""Версия 3: библиотеки знаний, редакции норм, юридическая проверка документов, мурабаха."""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.config import get_settings
from app.knowledge.service import edition_for, load_records
from app.models import Role
from app.services.common import today
from tests.conftest import staff_client
from tests.helpers import signed_deal


@pytest.fixture
def knowledge(monkeypatch, tmp_path) -> Path:
    target = tmp_path / "knowledge"
    shutil.copytree(Path(get_settings().knowledge_dir), target)
    monkeypatch.setattr(get_settings(), "knowledge_dir", target)
    return target


def edit_records(root: Path, library: str, fn) -> None:
    path = root / library / "records.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data["records"])
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def complete(record: dict) -> None:
    """Так запись выглядит после работы специалиста: даты, точная ссылка, дата сверки."""
    record.update(effective_from="2000-01-01", last_checked=today().isoformat(),
                  source_url=f"http://publication.pravo.gov.ru/document/test-{record['code']}")


def find(admin, code: str) -> dict:
    return next(i for i in admin.get("/api/admin/knowledge").json()["items"] if i["code"] == code)


def review(admin, code: str, version: str = "1", status: str = "approved"):
    return admin.post(f"/api/admin/knowledge/{code}/review", json={
        "version": version, "status": status, "reviewer_name": "Юрист Тестовый Т. Т.", "reviewer_role": "юрист"})


def test_library_is_honest_about_unverified_records(admin):
    data = admin.get("/api/admin/knowledge").json()
    assert {k: v["total"] for k, v in data["summary"].items()} == {"legal": 24, "accounting": 17, "islamic-finance": 8}
    assert not any(i["reliable"] for i in data["items"])
    gk = next(i for i in data["items"] if i["code"] == "legal.gk.489")
    joined = " ".join(gk["problems"])
    assert "не проверено" in joined and "не сверялась" in joined and "нет точной ссылки" in joined
    assert gk["act"].startswith("Гражданский кодекс") and gk["article"] == "ст. 489"


def test_review_is_bound_to_record_content(admin, knowledge):
    edit_records(knowledge, "legal", lambda rs: complete(next(r for r in rs if r["code"] == "legal.gk.489")))
    assert review(admin, "legal.gk.489").status_code == 200
    rec = find(admin, "legal.gk.489")
    assert rec["reliable"] and rec["review"]["reviewer_name"] == "Юрист Тестовый Т. Т."

    def change(rs):
        next(r for r in rs if r["code"] == "legal.gk.489")["summary"] += " Изменено."
    edit_records(knowledge, "legal", change)  # любое изменение текста снимает заключение
    rec = find(admin, "legal.gk.489")
    assert not rec["reliable"] and rec["review"] is None


def test_edition_is_chosen_by_contract_date(knowledge):
    def two_editions(rs):
        base = next(r for r in rs if r["code"] == "legal.gk.395")
        base.update(effective_from="2020-01-01", effective_to="2025-01-01")
        rs.append({**base, "version": "2", "effective_from": "2025-01-01", "effective_to": None,
                   "summary": base["summary"] + " Новая редакция."})
    edit_records(knowledge, "legal", two_editions)
    records = load_records()
    assert edition_for(records, "legal.gk.395", date(2024, 6, 1))[0].version == "1"
    assert edition_for(records, "legal.gk.395", date(2026, 6, 1))[0].version == "2"
    rec, note = edition_for(records, "legal.gk.395", date(2019, 6, 1))
    assert rec is None and "нет редакции" in note


def test_document_shows_legal_sources_and_editions(admin, knowledge):
    """Сценарий 17: юридическая проверка показывает нормы, редакцию и статус проверки."""
    _, _, contract = signed_deal(admin)
    doc = admin.post("/api/admin/documents", json={"template_code": "payment_schedule",
                                                   "contract_id": contract["id"]}).json()
    law = next(c for c in doc["checks"] if c["code"] == "law_version")
    assert law["level"] == "warning" and "Требуется проверка" in law["message"]
    assert {i["code"] for i in law["legal"]} == {"legal.gk.489", "if.murabaha.fixed_price"}
    assert next(i for i in law["legal"] if i["code"] == "legal.gk.489")["source"].endswith("ст. 489")

    edit_records(knowledge, "legal", lambda rs: complete(next(r for r in rs if r["code"] == "legal.gk.489")))
    edit_records(knowledge, "islamic-finance",
                 lambda rs: complete(next(r for r in rs if r["code"] == "if.murabaha.fixed_price")))
    review(admin, "legal.gk.489")
    review(admin, "if.murabaha.fixed_price")
    doc = admin.post(f"/api/admin/documents/{doc['id']}/regenerate").json()
    law = next(c for c in doc["checks"] if c["code"] == "law_version")
    assert law["level"] == "ok" and "проверены специалистами" in law["message"]


def test_expired_norm_is_reported(admin, knowledge):
    def expire(rs):
        r = next(r for r in rs if r["code"] == "legal.gk.429")
        complete(r)
        r["effective_to"] = (today() - timedelta(days=1)).isoformat()
    edit_records(knowledge, "legal", expire)
    rec = find(admin, "legal.gk.429")
    assert any("утратила силу" in p for p in rec["problems"])


def test_only_owner_records_specialist_conclusions(admin):
    manager = staff_client("manager@islamic-car.test", Role.manager)
    assert manager.get("/api/admin/knowledge").status_code == 200
    r = manager.post("/api/admin/knowledge/legal.gk.454/review", json={
        "version": "1", "status": "approved", "reviewer_name": "Кто-то", "reviewer_role": "юрист"})
    assert r.status_code == 403


def test_murabaha_checks_and_specialist_note(admin):
    _, _, contract = signed_deal(admin)
    data = admin.get(f"/api/admin/contracts/{contract['id']}/murabaha").json()
    states = {i["code"]: i["state"] for i in data["items"]}
    assert states["if.murabaha.ownership"] == "ok" and states["if.murabaha.cost_disclosure"] == "ok"
    assert states["if.murabaha.fixed_price"] == "ok" and states["if.murabaha.no_late_increase"] == "ok"
    assert data["failed"] == 0 and "уполномоченный специалист" in data["final_note"]
    assert data["rules_confirmed"] == 0  # правила библиотеки ещё не подтверждены специалистом
