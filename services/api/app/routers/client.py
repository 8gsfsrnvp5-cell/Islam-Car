"""Личный кабинет покупателя. Каждый запрос ограничен собственным client_id."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.documents.service import is_final
from app.models import (
    Addendum,
    AddendumStatus,
    Application,
    Audience,
    Channel,
    Consent,
    Contract,
    ContractStatus,
    Document,
    DocumentStatus,
    Notification,
    PaymentReport,
    PaymentStatus,
    SupportMessage,
    SupportThread,
    ThreadStatus,
)
from app.schemas import ClientConsentIn, MessageIn, PaymentReportIn, ThreadIn
from app.security import Actor, current_client
from app.serializers import (
    application_public,
    contract_client,
    payment_client,
    report_dict,
    thread_dict,
)
from app.services import audit, messaging
from app.services.common import today
from app.services.contracts import get_company, ledger_for
from app.services.export import csv_response, money
from app.services.notify import notify_staff, rub

router = APIRouter(prefix="/api/client", tags=["client"])

VISIBLE = (ContractStatus.signed, ContractStatus.completed)  # черновики покупатель не видит
STATUS_RU = {"paid": "Оплачен", "partial": "Оплачен частично", "overdue": "Просрочен",
             "due_today": "Срок сегодня", "upcoming": "Предстоит"}


def own_contract(db: Session, actor: Actor, contract_id: uuid.UUID) -> Contract:
    c = db.get(Contract, contract_id)
    # Одинаковый ответ для «чужого» и «несуществующего» — не раскрываем факт существования
    if not c or c.client_id != actor.user.client_id or c.status not in VISIBLE:
        raise HTTPException(404, "Договор не найден")
    return c


def own_thread(db: Session, actor: Actor, thread_id: uuid.UUID) -> SupportThread:
    t = db.get(SupportThread, thread_id)
    if not t or t.client_id != actor.user.client_id:
        raise HTTPException(404, "Обращение не найдено")
    return t


@router.get("/contracts")
def my_contracts(actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    contracts = db.scalars(select(Contract).where(
        Contract.client_id == actor.user.client_id, Contract.status.in_(VISIBLE))
        .order_by(Contract.signed_at.desc())).all()
    return [contract_client(c, ledger_for(db, c), with_rows=False) for c in contracts]


@router.get("/contracts/{contract_id}")
def my_contract(contract_id: uuid.UUID, actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    c = own_contract(db, actor, contract_id)
    data = contract_client(c, ledger_for(db, c))
    data["payments"] = [payment_client(p) for p in c.payments if p.status == PaymentStatus.confirmed]
    data["reports"] = [report_dict(r) for r in db.scalars(
        select(PaymentReport).where(PaymentReport.contract_id == c.id).order_by(PaymentReport.created_at.desc()))]
    return data


@router.get("/contracts/{contract_id}/schedule.csv")
def my_schedule_csv(contract_id: uuid.UUID, actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    c = own_contract(db, actor, contract_id)
    ledger = ledger_for(db, c)
    rows = [[f"График платежей по договору № {c.number}"], [f"Сформирован {today():%d.%m.%Y}"], [],
            ["№", "Вид", "Дата", "Сумма, руб.", "Оплачено, руб.", "Остаток, руб.", "Статус"]]
    for r in ledger.rows:
        rows.append([str(r.seq), "Первоначальный взнос" if r.kind == "down_payment" else "Ежемесячный платёж",
                     f"{r.due_date:%d.%m.%Y}", money(r.amount_kopecks), money(r.paid_kopecks),
                     money(r.remaining_kopecks), STATUS_RU[r.status]])
    rows += [[], ["Итого по договору", "", "", money(ledger.total_kopecks), money(ledger.paid_kopecks),
                  money(ledger.outstanding_kopecks), ""]]
    return csv_response(rows, f"schedule-{c.number}.csv")


@router.get("/contracts/{contract_id}/statement.csv")
def my_statement_csv(contract_id: uuid.UUID, actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    c = own_contract(db, actor, contract_id)
    ledger = ledger_for(db, c)
    rows = [[f"Выписка по платежам, договор № {c.number}"], [f"Сформирована {today():%d.%m.%Y}"], [],
            ["Дата поступления", "Сумма, руб."]]
    for p in c.payments:
        if p.status == PaymentStatus.confirmed:
            rows.append([f"{p.received_on:%d.%m.%Y}", money(p.amount_kopecks)])
    rows += [[], ["Цена договора", money(ledger.total_kopecks)], ["Оплачено", money(ledger.paid_kopecks)],
             ["Остаток", money(ledger.outstanding_kopecks)]]
    return csv_response(rows, f"statement-{c.number}.csv")


@router.post("/contracts/{contract_id}/payment-reports", status_code=201)
def report_payment(contract_id: uuid.UUID, data: PaymentReportIn, actor: Actor = Depends(current_client),
                   db: Session = Depends(get_db)):
    """«Я оплатил» — только сообщение. Платёж будет учтён после проверки сотрудником."""
    c = own_contract(db, actor, contract_id)
    if c.status != ContractStatus.signed:
        raise HTTPException(409, "Договор уже полностью оплачен")
    report = PaymentReport(contract_id=c.id, amount_kopecks=data.amount_kopecks, paid_on=data.paid_on,
                           comment=data.comment)
    db.add(report)
    notify_staff(db, "payment.reported", f"Покупатель сообщил об оплате: договор № {c.number}",
                 f"{rub(data.amount_kopecks)} от {data.paid_on:%d.%m.%Y}. Требуется сверка с банком.", "/payments")
    db.commit()
    return report_dict(report)


@router.get("/payment-info")
def payment_info(actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    co = get_company(db)
    configured = all([co.bank_payee, co.bank_account, co.bank_bik])
    return {"configured": configured, "payee": co.bank_payee, "bank_name": co.bank_name, "bik": co.bank_bik,
            "account": co.bank_account, "corr_account": co.bank_corr_account, "inn": co.seller_inn,
            "purpose_hint": co.payment_purpose_hint, "support_phone": co.support_phone}


@router.get("/applications")
def my_applications(actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    apps = db.scalars(select(Application).where(Application.client_id == actor.user.client_id)
                      .order_by(Application.created_at.desc())).all()
    return [application_public(a) for a in apps]


# --- Обращения (чат с менеджером) ---

@router.get("/threads")
def my_threads(actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    threads = db.scalars(select(SupportThread).where(SupportThread.client_id == actor.user.client_id)
                         .order_by(SupportThread.updated_at.desc())).all()
    return [thread_dict(t, with_messages=False, for_staff=False) for t in threads]


@router.post("/threads", status_code=201)
def create_thread(data: ThreadIn, actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    if data.contract_id:
        own_contract(db, actor, data.contract_id)
    t = SupportThread(client_id=actor.user.client_id, contract_id=data.contract_id, topic=data.topic,
                      subject=data.subject)
    db.add(t)
    db.flush()
    db.add(SupportMessage(thread_id=t.id, author_user_id=actor.user.id, from_staff=False, body=data.body))
    notify_staff(db, "support.new", f"Новое обращение: {data.subject}", actor.user.client.full_name,
                 f"/support/{t.id}")
    db.commit()
    db.refresh(t)
    return thread_dict(t, with_messages=True, for_staff=False)


@router.get("/threads/{thread_id}")
def get_thread(thread_id: uuid.UUID, actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    return thread_dict(own_thread(db, actor, thread_id), with_messages=True, for_staff=False)


@router.post("/threads/{thread_id}/messages", status_code=201)
def post_message(thread_id: uuid.UUID, data: MessageIn, actor: Actor = Depends(current_client),
                 db: Session = Depends(get_db)):
    t = own_thread(db, actor, thread_id)
    if t.status == ThreadStatus.closed:
        raise HTTPException(409, "Обращение закрыто. Создайте новое.")
    db.add(SupportMessage(thread_id=t.id, author_user_id=actor.user.id, from_staff=False, body=data.body))
    t.status = ThreadStatus.open
    t.updated_at = datetime.now(UTC)
    notify_staff(db, "support.message", f"Новое сообщение: {t.subject}", actor.user.client.full_name,
                 f"/support/{t.id}")
    db.commit()
    db.refresh(t)
    return thread_dict(t, with_messages=True, for_staff=False)


# --- Уведомления ---

@router.get("/notifications")
def my_notifications(actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    items = db.scalars(select(Notification).where(
        Notification.audience == Audience.client, Notification.client_id == actor.user.client_id)
        .order_by(Notification.created_at.desc()).limit(100)).all()
    return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
             "created_at": n.created_at, "read": n.read_at is not None} for n in items]


@router.post("/notifications/read-all")
def read_all(actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(
            Notification.audience == Audience.client, Notification.client_id == actor.user.client_id,
            Notification.read_at.is_(None))):
        n.read_at = datetime.now(UTC)
    db.commit()
    return {"ok": True}



# --- Версия 2: документы, согласия, изменения графика ---

CLIENT_DOC_STATUSES = (DocumentStatus.approved, DocumentStatus.signed)


def own_document(db: Session, actor: Actor, doc_id: uuid.UUID) -> Document:
    doc = db.get(Document, doc_id)
    contract = db.get(Contract, doc.contract_id) if doc and doc.contract_id else None
    if (not doc or not doc.visible_to_client or doc.status not in CLIENT_DOC_STATUSES or contract is None
            or contract.client_id != actor.user.client_id):
        raise HTTPException(404, "Документ не найден")
    return doc


@router.get("/documents")
def my_documents(actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    """Документы по договорам покупателя, которые утверждены или подписаны и предназначены ему."""
    rows = db.execute(select(Document, Contract.number).join(Contract, Contract.id == Document.contract_id).where(
        Contract.client_id == actor.user.client_id, Document.visible_to_client.is_(True),
        Document.status.in_(CLIENT_DOC_STATUSES)).order_by(Document.created_at.desc())).all()
    return [{"id": d.id, "title": d.title, "status": d.status, "contract_id": d.contract_id, "contract_number": number,
             "signed_on": d.signed_on, "final": is_final(d), "created_at": d.created_at} for d, number in rows]


@router.get("/documents/{doc_id}/export")
def my_document_export(doc_id: uuid.UUID, format: str = "pdf", actor: Actor = Depends(current_client),
                       db: Session = Depends(get_db)):
    from app.routers.admin_documents import export_response
    return export_response(own_document(db, actor, doc_id), format)


@router.get("/contracts/{contract_id}/schedule-changes")
def my_schedule_changes(contract_id: uuid.UUID, actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    c = own_contract(db, actor, contract_id)
    rows = db.scalars(select(Addendum).where(Addendum.contract_id == c.id, Addendum.status == AddendumStatus.signed)
                      .order_by(Addendum.number)).all()
    return [{"number": a.number, "signed_on": a.signed_on, "term_months": a.term_months,
             "first_payment_date": a.first_payment_date} for a in rows]


@router.get("/communications")
def my_communications(actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    c = actor.user.client
    consents = messaging.current_consents(db, c.id)
    return {"channels": [
        {"channel": "sms", "address": c.phone, "verified": c.phone_verified,
         "granted": bool(consents.get("sms", {}).get("granted"))},
        {"channel": "email", "address": c.email, "verified": c.email_verified,
         "granted": bool(consents.get("email", {}).get("granted"))},
    ]}


@router.post("/communications")
def set_my_consent(data: ClientConsentIn, actor: Actor = Depends(current_client), db: Session = Depends(get_db)):
    """Покупатель сам даёт или отзывает согласие на сервисные сообщения по каналу."""
    db.add(Consent(client_id=actor.user.client_id, channel=Channel(data.channel), granted=data.granted,
                   source="личный кабинет", recorded_by=actor.user.id))
    audit.record(db, actor, "client.consent_self", "client", actor.user.client_id, channel=data.channel,
                 granted=data.granted)
    db.commit()
    return my_communications(actor, db)
