"""Версия 2: конструктор документов, утверждение шаблонов, дополнительные соглашения."""

import io
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from docx import Document as DocxDocument

from app.config import get_settings
from app.services.common import today
from tests.helpers import (
    RUB,
    buyer_session,
    confirm_payment,
    create_car,
    create_contract,
    setup_company,
    signed_deal,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def templates(monkeypatch, tmp_path) -> Path:
    """Копия каталога шаблонов, чтобы тесты могли менять файлы."""
    target = tmp_path / "templates"
    shutil.copytree(Path(get_settings().templates_dir), target)
    monkeypatch.setattr(get_settings(), "templates_dir", target)
    return target


def docx_text(content: bytes) -> str:
    doc = DocxDocument(io.BytesIO(content))
    header = " ".join(p.text for p in doc.sections[0].header.paragraphs)
    return header + "\n" + "\n".join(p.text for p in doc.paragraphs)


def approve_template(admin, code: str):
    return admin.post(f"/api/admin/templates/{code}/approve", json={"lawyer_name": "Юрист Тестовый Т. Т.",
                                                                    "note": "проверено"})


def test_template_registry_lists_drafts_with_lawyer_points(admin):
    templates = {t["code"]: t for t in admin.get("/api/admin/templates").json()}
    assert len(templates) == 12
    sale = templates["sale_contract"]
    assert not sale["approved"] and len(sale["lawyer_points"]) >= 5
    # Шаблон с нерешёнными вопросами для юриста утвердить нельзя
    r = approve_template(admin, "sale_contract")
    assert r.status_code == 409 and r.json()["detail"]["points"]


def test_missing_data_is_requested_not_invented(admin):
    setup_company(admin)
    car = create_car(admin)
    client = admin.post("/api/admin/clients", json={"full_name": "Петров Пётр", "phone": "+79002223344"}).json()
    contract = create_contract(admin, client["id"], car["id"])
    r = admin.post("/api/admin/documents", json={"template_code": "sale_contract", "contract_id": contract["id"]})
    assert r.status_code == 422
    missing = " ".join(r.json()["detail"]["missing"])
    assert "адрес покупателя" in missing and "документ покупателя" in missing
    assert "Личность покупателя не подтверждена" in missing


def test_draft_from_unapproved_template_is_always_a_project(admin):
    _, _, contract = signed_deal(admin)
    r = admin.post("/api/admin/documents", json={"template_code": "sale_contract", "contract_id": contract["id"],
                                                 "params": {"place": "г. Тестовый", "require_insurance": True}})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "draft" and doc["final"] is False
    assert doc["watermark"] == "ПРОЕКТ · ШАБЛОН НЕ УТВЕРЖДЁН ЮРИСТОМ"
    codes = {c["code"] for c in doc["checks"]}
    assert {"required_fields", "arithmetic", "template", "law_version", "lawyer_point"} <= codes
    text = " ".join(b.get("text", "") for b in doc["blocks"])
    assert "1 600 000 (один миллион шестьсот тысяч) рублей 00 копеек" in text
    assert "1 200 000 (один миллион двести тысяч) рублей" in text  # раскрытие себестоимости
    assert "полис ОСАГО" in text

    pdf = admin.get(f"/api/admin/documents/{doc['id']}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    docx = admin.get(f"/api/admin/documents/{doc['id']}/export?format=docx")
    assert "ПРОЕКТ" in docx_text(docx.content) and "ДОГОВОР КУПЛИ-ПРОДАЖИ" in docx_text(docx.content)

    admin.post(f"/api/admin/documents/{doc['id']}/submit")
    assert admin.post(f"/api/admin/documents/{doc['id']}/approve").json()["final"] is False
    r = admin.post(f"/api/admin/documents/{doc['id']}/signed",
                   data={"signed_on": today().isoformat(), "confirm_paper_signed": "true"})
    assert r.status_code == 409  # проект не может стать подписанным документом


def test_approved_template_full_lifecycle_and_client_access(admin, templates):
    _, client, contract = signed_deal(admin)
    assert approve_template(admin, "payment_schedule").status_code == 200

    doc = admin.post("/api/admin/documents", json={"template_code": "payment_schedule",
                                                   "contract_id": contract["id"]}).json()
    assert doc["template_approved"] and doc["watermark"] == "ПРОЕКТ"  # черновик всё равно проект
    assert admin.post(f"/api/admin/documents/{doc['id']}/approve").status_code == 409  # без передачи на утверждение
    admin.post(f"/api/admin/documents/{doc['id']}/submit")
    approved = admin.post(f"/api/admin/documents/{doc['id']}/approve").json()
    assert approved["final"] is True and approved["watermark"] == ""
    assert "ПРОЕКТ" not in docx_text(admin.get(f"/api/admin/documents/{doc['id']}/export?format=docx").content)

    r = admin.post(f"/api/admin/documents/{doc['id']}/signed",
                   data={"signed_on": today().isoformat(), "confirm_paper_signed": "true"},
                   files={"file": ("scan.png", PNG, "image/png")})
    assert r.status_code == 200 and r.json()["status"] == "signed" and r.json()["has_signed_file"]
    # Подписанный документ неизменяем
    assert admin.post(f"/api/admin/documents/{doc['id']}/regenerate").status_code == 409
    assert admin.post(f"/api/admin/documents/{doc['id']}/cancel", json={"reason": "ошибка"}).status_code == 409
    assert admin.get(f"/api/admin/documents/{doc['id']}/signed-file").content == PNG

    buyer = buyer_session(admin, client["id"])
    mine = buyer.get("/api/client/documents").json()
    assert [d["id"] for d in mine] == [doc["id"]]
    assert buyer.get(f"/api/client/documents/{doc['id']}/export?format=pdf").content.startswith(b"%PDF")

    # Изменение файла шаблона делает утверждение недействительным
    (templates / "payment_schedule" / "template.md").write_text("# Изменённый шаблон\n", encoding="utf-8")
    t = {x["code"]: x for x in admin.get("/api/admin/templates").json()}["payment_schedule"]
    assert t["approved"] is False


def test_other_buyer_cannot_download_document(admin, templates):
    _, client_a, contract_a = signed_deal(admin)
    approve_template(admin, "reconciliation_act")
    doc = admin.post("/api/admin/documents", json={"template_code": "reconciliation_act",
                                                   "contract_id": contract_a["id"]}).json()
    admin.post(f"/api/admin/documents/{doc['id']}/submit")
    admin.post(f"/api/admin/documents/{doc['id']}/approve")

    car_b = create_car(admin, vin="XTA21099087654321")
    from tests.helpers import create_verified_client, sign
    client_b = create_verified_client(admin, phone="+79005556677", name="Сидоров Сидор")
    sign(admin, create_contract(admin, client_b["id"], car_b["id"]))
    buyer_b = buyer_session(admin, client_b["id"])
    assert buyer_b.get(f"/api/client/documents/{doc['id']}/export").status_code == 404
    assert buyer_b.get("/api/client/documents").json() == []


def test_condition_based_documents(admin):
    _, _, contract = signed_deal(admin)
    r = admin.post("/api/admin/documents", json={"template_code": "overdue_notice", "contract_id": contract["id"]})
    assert r.status_code == 422 and "просроченная задолженность" in " ".join(r.json()["detail"]["missing"])
    r = admin.post("/api/admin/documents", json={"template_code": "completion_confirmation",
                                                 "contract_id": contract["id"]})
    assert r.status_code == 422
    confirm_payment(admin, contract["id"], 1_600_000)
    r = admin.post("/api/admin/documents", json={"template_code": "completion_confirmation",
                                                 "contract_id": contract["id"]})
    assert r.status_code == 201


def test_schedule_addendum_keeps_price_and_history(admin, templates):
    _, client, contract = signed_deal(admin)
    confirm_payment(admin, contract["id"], 650_000)  # взнос и часть первого платежа
    assert approve_template(admin, "schedule_addendum").status_code == 200
    first = (today() + timedelta(days=40)).isoformat()

    past = admin.post(f"/api/admin/contracts/{contract['id']}/addenda/preview",
                      json={"term_months": 30, "first_payment_date": (today() - timedelta(days=1)).isoformat()})
    assert past.status_code == 422
    preview = admin.post(f"/api/admin/contracts/{contract['id']}/addenda/preview",
                         json={"term_months": 30, "first_payment_date": first}).json()
    assert all(c["ok"] for c in preview["checks"])
    assert sum(r["amount_kopecks"] for r in preview["new_schedule"]) == 1_600_000 * RUB

    created = admin.post(f"/api/admin/contracts/{contract['id']}/addenda",
                         json={"term_months": 30, "first_payment_date": first,
                               "reason": "Просьба покупателя: временное снижение дохода"}).json()
    assert admin.post(f"/api/admin/contracts/{contract['id']}/addenda",
                      json={"term_months": 10, "first_payment_date": first}).status_code == 409
    doc_id = created["document_id"]
    admin.post(f"/api/admin/documents/{doc_id}/submit")
    admin.post(f"/api/admin/documents/{doc_id}/approve")
    r = admin.post(f"/api/admin/documents/{doc_id}/signed",
                   data={"signed_on": today().isoformat(), "confirm_paper_signed": "true"})
    assert r.status_code == 200, r.text

    view = admin.get(f"/api/admin/contracts/{contract['id']}").json()
    rows = view["ledger"]["rows"]
    assert view["ledger"]["total_kopecks"] == 1_600_000 * RUB  # цена не изменилась
    assert view["ledger"]["outstanding_kopecks"] == 950_000 * RUB
    assert rows[0]["paid_kopecks"] == 600_000 * RUB and rows[1]["amount_kopecks"] == 50_000 * RUB
    assert len(rows) == 2 + 30 and all(r["status"] != "overdue" for r in rows)
    history = admin.get(f"/api/admin/contracts/{contract['id']}/addenda").json()
    assert len(history["history"]) == 21 and history["addenda"][0]["status"] == "signed"

    buyer = buyer_session(admin, client["id"])
    changes = buyer.get(f"/api/client/contracts/{contract['id']}/schedule-changes").json()
    assert changes[0]["number"] == 1 and changes[0]["term_months"] == 30
    assert isinstance(view["ledger"]["paid_kopecks"], int)  # суммы — целые копейки и на PostgreSQL
