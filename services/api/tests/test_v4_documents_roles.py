"""Версия 4: автоматическая проверка документов, агент документов, роли юриста, специалиста по шариату, аудитора."""

import uuid

from sqlalchemy import select

from app.agents.base import run_agent
from app.agents.registry import AGENTS
from app.config import get_settings
from app.db import SessionLocal
from app.models import Document, Role, StaffTask
from tests.conftest import staff_client
from tests.helpers import COMPANY, signed_deal

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def issues(admin, contract_id: str | None = None) -> list[dict]:
    r = admin.get("/api/admin/document-audit" + (f"?contract_id={contract_id}" if contract_id else ""))
    assert r.status_code == 200, r.text
    return r.json()["issues"]


def new_schedule_doc(admin, contract_id: str) -> dict:
    r = admin.post("/api/admin/documents", json={"template_code": "payment_schedule", "contract_id": contract_id})
    assert r.status_code == 201, r.text
    return r.json()


def test_document_audit_finds_stale_missing_and_broken_files(admin):
    _, client, contract = signed_deal(admin)
    lawyer = staff_client("lawyer1", Role.lawyer)
    r = lawyer.post("/api/admin/templates/payment_schedule/approve", json={"lawyer_name": "Юрист Тестовый Т. Т."})
    assert r.status_code == 200, r.text

    signed = new_schedule_doc(admin, contract["id"])
    admin.post(f"/api/admin/documents/{signed['id']}/submit")
    admin.post(f"/api/admin/documents/{signed['id']}/approve")
    r = admin.post(f"/api/admin/documents/{signed['id']}/signed",
                   data={"signed_on": contract["contract_date"], "confirm_paper_signed": "true"},
                   files={"file": ("scan.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    draft = new_schedule_doc(admin, contract["id"])

    found = issues(admin, contract["id"])
    codes = {(i["code"], i["document_id"]) for i in found}
    assert ("missing", None) in codes  # нет договора купли-продажи и акта приёма-передачи
    assert sum(1 for i in found if i["code"] == "missing") == 2
    assert not any(i["code"] in ("stale", "scan_changed", "body_tampered") for i in found)

    # Реквизиты продавца изменились после формирования черновика
    r = admin.put("/api/admin/settings", json={**COMPANY, "seller_address": "г. Тестовый, ул. Новая, 5"})
    assert r.status_code == 200, r.text
    stale = [i for i in issues(admin) if i["code"] == "stale"]
    assert [i["document_id"] for i in stale] == [draft["id"]]  # подписанный документ — история, он не «устаревает»
    assert "реквизиты продавца" in stale[0]["message"]

    # Подмена скана и текста в обход системы
    with SessionLocal() as db:
        doc = db.get(Document, uuid.UUID(signed["id"]))
        (get_settings().storage_dir / "documents" / doc.signed_file_name).write_bytes(PNG + b"changed")
        other = db.get(Document, uuid.UUID(draft["id"]))
        other.body = other.body + "\nдописано"
        db.commit()
    found = issues(admin)
    assert {"scan_changed", "body_tampered"} <= {i["code"] for i in found if i["severity"] == "critical"}

    # Агент документов ставит задачи по критичным замечаниям, повторный запуск их не дублирует
    run_agent(AGENTS["documents"])
    run_agent(AGENTS["documents"])
    with SessionLocal() as db:
        titles = [t.title for t in db.scalars(select(StaffTask).where(StaffTask.kind == "agent_document"))]
    assert len(titles) == 2 and any("скан изменён" in t for t in titles)


def test_document_audit_permissions(admin):
    signed_deal(admin)
    assert staff_client("auditor1", Role.auditor).get("/api/admin/document-audit").status_code == 200
    assert staff_client("accountant1", Role.accountant).get("/api/admin/document-audit").status_code == 403


def first_record(admin, library: str) -> dict:
    items = admin.get(f"/api/admin/knowledge?library={library}").json()["items"]
    return items[0]


def review(c, record: dict):
    return c.post(f"/api/admin/knowledge/{record['code']}/review", json={
        "version": record["version"], "status": "approved", "reviewer_name": "Специалист Тестовый",
        "reviewer_role": "специалист", "note": "проверено по официальному источнику"})


def test_library_reviews_by_specialist_role(admin):
    legal, islamic, accounting = (first_record(admin, lib) for lib in ("legal", "islamic-finance", "accounting"))
    lawyer = staff_client("lawyer1", Role.lawyer)
    shariah = staff_client("shariah1", Role.shariah_advisor)
    accountant = staff_client("accountant1", Role.accountant)
    manager = staff_client("manager1", Role.manager)
    assert review(lawyer, legal).status_code == 200
    assert review(lawyer, islamic).status_code == 403
    assert review(shariah, islamic).status_code == 200
    assert review(shariah, accounting).status_code == 403
    assert review(accountant, accounting).status_code == 200
    assert review(accountant, legal).status_code == 403
    assert review(manager, legal).status_code == 403
    assert manager.post("/api/admin/templates/payment_schedule/approve",
                        json={"lawyer_name": "Юрист Тестовый Т. Т."}).status_code == 403


def test_auditor_is_read_only_with_masked_personal_data(admin):
    _, client, contract = signed_deal(admin)
    auditor = staff_client("auditor1", Role.auditor)
    for path in ("/api/admin/dashboard", "/api/admin/audit", "/api/admin/analytics", f"/api/admin/contracts/"
                 f"{contract['id']}", "/api/admin/bank/transactions", "/api/admin/finance/position"):
        assert auditor.get(path).status_code == 200, path
    card = auditor.get(f"/api/admin/clients/{client['id']}").json()
    assert card["pd_masked"] is True and card["passport_number"] != "0000 000000"
    assert auditor.post("/api/admin/cars", json={}).status_code == 403
    assert auditor.post("/api/admin/payments", json={}).status_code == 403
    assert auditor.get("/api/admin/threads").status_code == 403  # переписка с покупателями — персональные данные
    me = auditor.get("/api/auth/admin/me").json()
    assert not [p for p in me["permissions"] if p.endswith((".write", ".confirm", ".sign", ".manage"))]


def test_shariah_advisor_sees_murabaha_check_but_not_payments(admin):
    _, _, contract = signed_deal(admin)
    shariah = staff_client("shariah1", Role.shariah_advisor)
    assert shariah.get(f"/api/admin/contracts/{contract['id']}/murabaha").status_code == 200
    assert shariah.get("/api/admin/bank/transactions").status_code == 403
