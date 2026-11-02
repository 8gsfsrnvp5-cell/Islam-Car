"""Конструктор документов, утверждение шаблонов, дополнительные соглашения об изменении графика."""

import hashlib
import uuid
from datetime import UTC, date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.documents import registry
from app.documents.render import FontNotFound, to_docx, to_pdf
from app.documents.service import blocks_for, compose, create_document, footer, is_final, watermark
from app.models import (
    Addendum,
    AddendumStatus,
    Car,
    Client,
    Contract,
    Document,
    DocumentStatus,
    ScheduleHistory,
    TemplateApproval,
)
from app.schemas import AddendumIn, DocumentIn, ReasonIn, TemplateApproveIn
from app.security import Actor, require
from app.services import audit
from app.services.addenda import apply_addendum, create_addendum, plan_schedule
from app.services.common import today
from app.services.notify import notify_client, notify_staff

router = APIRouter(prefix="/api/admin", tags=["admin: documents"])

SIGNED_TYPES = {b"%PDF": ("application/pdf", ".pdf"), b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
                b"\x89PNG\r\n\x1a\n": ("image/png", ".png")}


def docs_dir():
    d = get_settings().storage_dir / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def template_dict(db: Session, tpl: registry.Template) -> dict:
    approval = registry.active_approval(db, tpl)
    return {"code": tpl.code, "title": tpl.title, "version": tpl.version, "scope": tpl.scope,
            "description": tpl.description, "requires": tpl.requires, "params": tpl.params,
            "requires_signed_contract": tpl.requires_signed_contract, "visible_to_client": tpl.visible_to_client,
            "legal_refs": tpl.legal_refs,
            "sha256": tpl.sha256, "lawyer_points": tpl.lawyer_points,
            "approved": approval is not None,
            "approval": {"lawyer_name": approval.lawyer_name, "approved_at": approval.approved_at,
                         "note": approval.note} if approval else None}


def document_dict(doc: Document, with_body: bool = False) -> dict:
    data = {"id": doc.id, "title": doc.title, "template_code": doc.template_code,
            "template_version": doc.template_version,
            "template_approved": doc.template_approved, "status": doc.status, "contract_id": doc.contract_id,
            "client_id": doc.client_id, "addendum_id": doc.addendum_id, "visible_to_client": doc.visible_to_client,
            "created_at": doc.created_at, "submitted_at": doc.submitted_at, "approved_at": doc.approved_at,
            "signed_on": doc.signed_on, "has_signed_file": bool(doc.signed_file_name), "final": is_final(doc),
            "watermark": watermark(doc), "body_sha256": doc.body_sha256, "cancelled_reason": doc.cancelled_reason,
            "checks": doc.checks}
    if with_body:
        data["blocks"] = blocks_for(doc)
        data["params"] = doc.data.get("params", {})
    return data


# --- Шаблоны ---------------------------------------------------------------------

@router.get("/templates")
def list_templates(actor: Actor = Depends(require("contracts.read")), db: Session = Depends(get_db)):
    return [template_dict(db, t) for t in registry.load_templates().values()]


@router.post("/templates/{code}/approve")
def approve_template(code: str, data: TemplateApproveIn, actor: Actor = Depends(require("settings.write")),
                     db: Session = Depends(get_db)):
    """Фиксирует утверждение шаблона юристом. Шаблон со спорными пометками утвердить нельзя."""
    tpl = registry.get_template(code)
    if not tpl:
        raise HTTPException(404, "Шаблон не найден")
    if tpl.lawyer_points:
        raise HTTPException(409, {"message": "В шаблоне остались пометки для юриста — сначала внесите решения в текст",
                                  "points": tpl.lawyer_points})
    approval = TemplateApproval(template_code=tpl.code, version=tpl.version, content_sha256=tpl.sha256,
                                lawyer_name=data.lawyer_name, note=data.note, approved_by=actor.user.id)
    db.add(approval)
    audit.record(db, actor, "template.approved", "template", tpl.code, version=tpl.version, sha256=tpl.sha256,
                 lawyer=data.lawyer_name)
    db.commit()
    return template_dict(db, tpl)


@router.post("/templates/{code}/revoke")
def revoke_template(code: str, actor: Actor = Depends(require("settings.write")), db: Session = Depends(get_db)):
    tpl = registry.get_template(code)
    approval = registry.active_approval(db, tpl) if tpl else None
    if not approval:
        raise HTTPException(404, "Действующего утверждения нет")
    approval.revoked_at = datetime.now(UTC)
    audit.record(db, actor, "template.approval_revoked", "template", code)
    db.commit()
    return template_dict(db, tpl)


# --- Документы -----------------------------------------------------------------------

def get_doc(db: Session, doc_id: uuid.UUID) -> Document:
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    return doc


def _sources(db: Session, data: DocumentIn, tpl: registry.Template):
    contract = client = car = addendum = None
    if data.addendum_id:
        addendum = db.get(Addendum, data.addendum_id)
        if not addendum:
            raise HTTPException(404, "Дополнительное соглашение не найдено")
        contract = db.get(Contract, addendum.contract_id)
    elif data.contract_id:
        contract = db.get(Contract, data.contract_id)
        if not contract:
            raise HTTPException(404, "Договор не найден")
    if tpl.scope == "contract" and contract is None:
        raise HTTPException(422, "Для этого документа выберите договор")
    if data.client_id:
        client = db.get(Client, data.client_id)
    if data.car_id:
        car = db.get(Car, data.car_id)
    if tpl.scope == "client" and client is None:
        raise HTTPException(422, "Для этого документа выберите клиента")
    if tpl.code == "schedule_addendum" and addendum is None:
        raise HTTPException(422, "Документ формируется из дополнительного соглашения")
    return contract, client, car, addendum


@router.get("/documents")
def list_documents(contract_id: uuid.UUID | None = None, status: DocumentStatus | None = None,
                   actor: Actor = Depends(require("contracts.read")), db: Session = Depends(get_db)):
    stmt = select(Document).order_by(Document.created_at.desc()).limit(500)
    if contract_id:
        stmt = stmt.where(Document.contract_id == contract_id)
    if status:
        stmt = stmt.where(Document.status == status)
    return [document_dict(d) for d in db.scalars(stmt)]


@router.post("/documents/preview")
def preview_document(data: DocumentIn, actor: Actor = Depends(require("contracts.write")),
                     db: Session = Depends(get_db)):
    """Проверки и текст без сохранения. При нехватке данных — 422 со списком."""
    tpl = registry.get_template(data.template_code)
    if not tpl:
        raise HTTPException(404, "Шаблон не найден")
    contract, client, car, addendum = _sources(db, data, tpl)
    composed = compose(db, tpl, contract=contract, client=client, car=car, addendum=addendum, params=data.params,
                       today=today())
    from app.documents.markup import parse
    db.rollback()
    return {"title": composed["title"], "checks": composed["checks"], "approved": composed["approved"],
            "blocks": parse(composed["text"], composed["ctx"])}


@router.post("/documents", status_code=201)
def create(data: DocumentIn, actor: Actor = Depends(require("contracts.write")), db: Session = Depends(get_db)):
    tpl = registry.get_template(data.template_code)
    if not tpl:
        raise HTTPException(404, "Шаблон не найден")
    contract, client, car, addendum = _sources(db, data, tpl)
    doc = create_document(db, tpl, contract=contract, client=client, car=car, addendum=addendum, params=data.params,
                          today=today(), user_id=actor.user.id)
    audit.record(db, actor, "document.created", "document", doc.id, template=tpl.code, version=tpl.version,
                 contract=data.contract_id, approved_template=doc.template_approved)
    db.commit()
    return document_dict(doc, with_body=True)


@router.get("/documents/{doc_id}")
def read_document(doc_id: uuid.UUID, actor: Actor = Depends(require("contracts.read")), db: Session = Depends(get_db)):
    return document_dict(get_doc(db, doc_id), with_body=True)


@router.post("/documents/{doc_id}/regenerate")
def regenerate(doc_id: uuid.UUID, actor: Actor = Depends(require("contracts.write")), db: Session = Depends(get_db)):
    """Пересобирает черновик из актуальных карточек. Утверждённый и подписанный документ не меняется."""
    doc = get_doc(db, doc_id)
    if doc.status != DocumentStatus.draft:
        raise HTTPException(409, "Пересобрать можно только черновик")
    tpl = registry.get_template(doc.template_code)
    if not tpl:
        raise HTTPException(404, "Шаблон больше не существует")
    contract = db.get(Contract, doc.contract_id) if doc.contract_id else None
    addendum = db.get(Addendum, doc.addendum_id) if doc.addendum_id else None
    sources = doc.data.get("sources", {})
    client = db.get(Client, uuid.UUID(sources["client_id"])) if sources.get("client_id") else None
    car = db.get(Car, uuid.UUID(sources["car_id"])) if sources.get("car_id") else None
    composed = compose(db, tpl, contract=contract, client=client, car=car, addendum=addendum,
                       params=doc.data.get("params", {}), today=today())
    doc.body = composed["text"]
    doc.body_sha256 = hashlib.sha256(doc.body.encode()).hexdigest()
    doc.checks = composed["checks"]
    doc.data = {"params": composed["ctx"]["params"], "ctx": composed["ctx"], "sources": sources}
    doc.template_version, doc.template_sha256, doc.template_approved = tpl.version, tpl.sha256, composed["approved"]
    audit.record(db, actor, "document.regenerated", "document", doc.id)
    db.commit()
    return document_dict(doc, with_body=True)


@router.post("/documents/{doc_id}/submit")
def submit(doc_id: uuid.UUID, actor: Actor = Depends(require("contracts.write")), db: Session = Depends(get_db)):
    doc = get_doc(db, doc_id)
    if doc.status != DocumentStatus.draft:
        raise HTTPException(409, "На утверждение передаётся только черновик")
    doc.status = DocumentStatus.pending_approval
    doc.submitted_at = datetime.now(UTC)
    notify_staff(db, "document.pending", f"Документ ожидает утверждения: {doc.title}", "", f"/documents/{doc.id}")
    audit.record(db, actor, "document.submitted", "document", doc.id)
    db.commit()
    return document_dict(doc, with_body=True)


@router.post("/documents/{doc_id}/approve")
def approve(doc_id: uuid.UUID, actor: Actor = Depends(require("contracts.sign")), db: Session = Depends(get_db)):
    """Утверждение ответственным лицом. Без утверждённого шаблона документ остаётся проектом."""
    doc = get_doc(db, doc_id)
    if doc.status != DocumentStatus.pending_approval:
        raise HTTPException(409, "Утвердить можно документ, переданный на утверждение")
    if any(c.get("level") == "error" for c in doc.checks):
        raise HTTPException(409, "В документе есть непройденные проверки")
    doc.status = DocumentStatus.approved
    doc.approved_by = actor.user.id
    doc.approved_at = datetime.now(UTC)
    audit.record(db, actor, "document.approved", "document", doc.id, final=is_final(doc))
    db.commit()
    return document_dict(doc, with_body=True)


@router.post("/documents/{doc_id}/cancel")
def cancel(doc_id: uuid.UUID, data: ReasonIn, actor: Actor = Depends(require("contracts.write")),
           db: Session = Depends(get_db)):
    doc = get_doc(db, doc_id)
    if doc.status == DocumentStatus.signed:
        raise HTTPException(409, "Подписанный документ не отменяется — оформите новый документ")
    doc.status = DocumentStatus.cancelled
    doc.cancelled_reason = data.reason
    if doc.addendum_id:
        addendum = db.get(Addendum, doc.addendum_id)
        if addendum and addendum.status == AddendumStatus.draft:
            addendum.status = AddendumStatus.cancelled
    audit.record(db, actor, "document.cancelled", "document", doc.id, reason=data.reason)
    db.commit()
    return document_dict(doc, with_body=True)


@router.post("/documents/{doc_id}/signed")
async def mark_signed(doc_id: uuid.UUID, signed_on: date = Form(...), confirm_paper_signed: bool = Form(...),
                      file: UploadFile | None = File(None), actor: Actor = Depends(require("contracts.sign")),
                      db: Session = Depends(get_db)):
    """Фиксирует подписание сторонами (по желанию — со сканом). После этого документ неизменяем."""
    doc = get_doc(db, doc_id)
    if not confirm_paper_signed:
        raise HTTPException(422, "Подтвердите, что документ подписан сторонами")
    if doc.status != DocumentStatus.approved:
        raise HTTPException(409, "Подписать можно только утверждённый документ")
    if not doc.template_approved:
        raise HTTPException(409, "Документ из неутверждённого шаблона — это проект, подписывать его как окончательный "
                                 "нельзя. Утвердите шаблон у юриста и сформируйте документ заново.")
    if file is not None and file.filename:
        limit = get_settings().max_document_bytes
        content = await file.read(limit + 1)
        if len(content) > limit:
            raise HTTPException(413, "Файл слишком большой")
        kind = next((v for sig, v in SIGNED_TYPES.items() if content.startswith(sig)), None)
        if not kind:
            raise HTTPException(415, "Скан принимается в формате PDF, JPEG или PNG")
        name = f"{uuid.uuid4().hex}{kind[1]}"
        (docs_dir() / name).write_bytes(content)
        doc.signed_file_name, doc.signed_file_type = name, kind[0]
        doc.signed_file_sha256 = hashlib.sha256(content).hexdigest()
    if doc.addendum_id:
        apply_addendum(db, db.get(Addendum, doc.addendum_id), signed_on, today())
        contract = db.get(Contract, doc.contract_id)
        notify_client(db, contract.client_id, "contract.schedule_changed",
                      f"График по договору № {contract.number} изменён дополнительным соглашением",
                      "Цена договора не изменилась. Новый график — в личном кабинете.",
                      f"/cabinet/contracts/{contract.id}")
    doc.status = DocumentStatus.signed
    doc.signed_on = signed_on
    doc.signed_recorded_by = actor.user.id
    audit.record(db, actor, "document.signed", "document", doc.id, signed_on=signed_on,
                 file_sha256=doc.signed_file_sha256 or None)
    db.commit()
    return document_dict(doc, with_body=True)


def export_response(doc: Document, fmt: str) -> Response:
    blocks = blocks_for(doc)
    mark, foot = watermark(doc), footer(doc)
    try:
        if fmt == "pdf":
            content, media, ext = to_pdf(blocks, mark, foot), "application/pdf", "pdf"
        elif fmt == "docx":
            content = to_docx(blocks, mark, foot)
            media, ext = "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"
        else:
            raise HTTPException(422, "Формат: pdf или docx")
    except FontNotFound as e:
        raise HTTPException(500, str(e)) from None
    prefix = "" if is_final(doc) else "ПРОЕКТ - "
    filename = f"{prefix}{doc.title}.{ext}".replace("/", "-").replace("\\", "-")
    return Response(content, media_type=media, headers={
        "Content-Disposition": f"attachment; filename=\"document.{ext}\"; filename*=UTF-8''{quote(filename)}"})


@router.get("/documents/{doc_id}/export")
def export(doc_id: uuid.UUID, format: str = "pdf", actor: Actor = Depends(require("contracts.read")),
           db: Session = Depends(get_db)):
    return export_response(get_doc(db, doc_id), format)


@router.get("/documents/{doc_id}/signed-file")
def signed_file(doc_id: uuid.UUID, actor: Actor = Depends(require("contracts.read")), db: Session = Depends(get_db)):
    doc = get_doc(db, doc_id)
    if not doc.signed_file_name:
        raise HTTPException(404, "Скан не загружен")
    return FileResponse(docs_dir() / doc.signed_file_name, media_type=doc.signed_file_type)


# --- Дополнительные соглашения ------------------------------------------------------

def addendum_dict(a: Addendum) -> dict:
    return {"id": a.id, "number": a.number, "status": a.status, "reason": a.reason, "term_months": a.term_months,
            "first_payment_date": a.first_payment_date, "new_schedule": a.new_schedule, "old_schedule": a.old_schedule,
            "base_paid_kopecks": a.base_paid_kopecks, "created_at": a.created_at, "signed_on": a.signed_on,
            "thread_id": a.thread_id}


@router.post("/contracts/{contract_id}/addenda/preview")
def addendum_preview(contract_id: uuid.UUID, data: AddendumIn, actor: Actor = Depends(require("contracts.write")),
                     db: Session = Depends(get_db)):
    c = db.get(Contract, contract_id)
    if not c:
        raise HTTPException(404, "Договор не найден")
    rows, paid, checks = plan_schedule(db, c, data.term_months, data.first_payment_date, today())
    return {"new_schedule": rows, "paid_kopecks": paid, "checks": checks,
            "monthly_kopecks": rows[-2]["amount_kopecks"] if len(rows) > 1 else rows[-1]["amount_kopecks"]}


@router.post("/contracts/{contract_id}/addenda", status_code=201)
def addendum_create(contract_id: uuid.UUID, data: AddendumIn, actor: Actor = Depends(require("contracts.write")),
                    db: Session = Depends(get_db)):
    """Создаёт соглашение и сразу формирует его документ из шаблона."""
    c = db.get(Contract, contract_id)
    if not c:
        raise HTTPException(404, "Договор не найден")
    a = create_addendum(db, c, data.term_months, data.first_payment_date, data.reason, data.thread_id, actor.user.id,
                        today())
    tpl = registry.get_template("schedule_addendum")
    if not tpl:
        raise HTTPException(500, "Нет шаблона дополнительного соглашения")
    doc = create_document(db, tpl, contract=c, client=None, car=None, addendum=a, params={}, today=today(),
                          user_id=actor.user.id)
    audit.record(db, actor, "addendum.created", "addendum", a.id, contract=c.number, term=data.term_months)
    db.commit()
    return {**addendum_dict(a), "document_id": doc.id}


@router.get("/contracts/{contract_id}/addenda")
def addendum_list(contract_id: uuid.UUID, actor: Actor = Depends(require("contracts.read")),
                  db: Session = Depends(get_db)):
    rows = db.scalars(select(Addendum).where(Addendum.contract_id == contract_id).order_by(Addendum.number)).all()
    docs = {d.addendum_id: d.id for d in db.scalars(select(Document).where(
        Document.contract_id == contract_id, Document.addendum_id.is_not(None),
        Document.status != DocumentStatus.cancelled))}
    history = db.scalars(select(ScheduleHistory).where(ScheduleHistory.contract_id == contract_id)
                         .order_by(ScheduleHistory.version, ScheduleHistory.seq)).all()
    return {"addenda": [{**addendum_dict(a), "document_id": docs.get(a.id)} for a in rows],
            "history": [{"version": h.version, "seq": h.seq, "due_date": h.due_date, "amount_kopecks": h.amount_kopecks}
                        for h in history]}
