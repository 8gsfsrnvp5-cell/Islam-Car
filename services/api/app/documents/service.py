"""Формирование документа: шаблон → проверенные данные → проверки → проект → утверждение → экспорт."""

import hashlib
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.documents.context import build_context, missing_fields
from app.documents.markup import lawyer_points, parse, render_text
from app.documents.registry import Template, active_approval
from app.models import Addendum, Car, Client, Contract, ContractStatus, Document, DocumentStatus


def run_checks(db: Session, tpl: Template, ctx: dict, contract: Contract | None, addendum: Addendum | None,
               approved: bool, text: str | None) -> tuple[list[dict], list[str]]:
    """Проверки перед формированием. Второй элемент — недостающие обязательные данные (блокируют)."""
    checks: list[dict] = []
    missing = missing_fields(ctx, tpl.requires)
    for m in tpl.params:
        if m.get("required") and not str(ctx["params"].get(m["name"], "")).strip():
            missing.append(m["label"])
    checks.append({"code": "required_fields", "level": "ok" if not missing else "error",
                   "message": "Все обязательные данные заполнены" if not missing
                   else "Не хватает данных: " + "; ".join(missing)})

    if contract is not None:
        total = sum(i.amount_kopecks for i in contract.schedule)
        ok = total == contract.sale_price_kopecks
        checks.append({"code": "arithmetic", "level": "ok" if ok else "error",
                       "message": "Сумма графика равна цене договора" if ok
                       else "Сумма графика не равна цене договора"})
        if tpl.requires_signed_contract and contract.status not in (ContractStatus.signed, ContractStatus.completed):
            checks.append({"code": "contract_status", "level": "error",
                           "message": "Документ формируется только по подписанному договору"})
        if not contract.client.identity_verified:
            checks.append({"code": "identity", "level": "error" if tpl.code == "sale_contract" else "warning",
                           "message": "Личность покупателя не подтверждена сотрудником"})
        if contract.is_consumer_deal:
            checks.append({"code": "consumer", "level": "info",
                           "message": "Потребительская сделка: условия должны соответствовать Закону о защите прав "
                                      "потребителей"})
        checks.append({"code": "no_interest", "level": "ok" if contract.no_interest_on_delay else "error",
                       "message": "Проценты и штрафы за просрочку не предусмотрены"})
    if addendum is not None:
        total = sum(r["amount_kopecks"] for r in addendum.new_schedule)
        ok = contract is not None and total == contract.sale_price_kopecks
        checks.append({"code": "addendum_total", "level": "ok" if ok else "error",
                       "message": "Новый график не меняет цену договора" if ok
                       else "Новый график меняет цену договора"})

    checks.append({"code": "template", "level": "ok" if approved else "warning",
                   "message": "Шаблон утверждён юристом" if approved else
                   "Шаблон не утверждён юристом: документ будет помечен «ПРОЕКТ», окончательная версия недоступна"})
    checks.append({"code": "law_version", "level": "warning",
                   "message": "Актуальность норм права автоматически не проверяется (библиотека знаний — версия 3). "
                              "Требуется проверка юриста."})
    for point in lawyer_points(text or tpl.body):
        checks.append({"code": "lawyer_point", "level": "warning", "message": f"Спорное условие: {point}"})
    blocking = missing + [c["message"] for c in checks if c["level"] == "error" and c["code"] != "required_fields"]
    return checks, blocking


def _title(tpl: Template, contract: Contract | None, addendum: Addendum | None) -> str:
    if addendum is not None and contract is not None:
        return f"{tpl.title} № {addendum.number} к договору № {contract.number}"
    if contract is not None and contract.number:
        return f"{tpl.title} — договор № {contract.number}"
    if contract is not None:
        return f"{tpl.title} — проект к договору ({contract.car.make} {contract.car.model})"
    return tpl.title


def compose(db: Session, tpl: Template, *, contract: Contract | None, client: Client | None, car: Car | None,
            addendum: Addendum | None, params: dict, today: date) -> dict:
    # Необязательные параметры шаблона всегда определены — шаблоны работают со строгой подстановкой
    params = {**{p["name"]: (False if p.get("type") == "bool" else "") for p in tpl.params}, **(params or {})}
    ctx = build_context(db, contract=contract, client=client, car=car, addendum=addendum, params=params,
                        today=today)
    approval = active_approval(db, tpl)
    checks, blocking = run_checks(db, tpl, ctx, contract, addendum, approval is not None, None)
    if blocking:
        raise HTTPException(422, {"message": "Документ не может быть сформирован", "missing": blocking,
                                  "checks": checks})
    text = render_text(tpl.body, ctx)
    checks, _ = run_checks(db, tpl, ctx, contract, addendum, approval is not None, text)
    return {"ctx": ctx, "text": text, "checks": checks, "approved": approval is not None,
            "title": _title(tpl, contract, addendum)}


def create_document(db: Session, tpl: Template, *, contract: Contract | None, client: Client | None,
                    car: Car | None, addendum: Addendum | None, params: dict, today: date, user_id) -> Document:
    composed = compose(db, tpl, contract=contract, client=client, car=car, addendum=addendum, params=params,
                       today=today)
    doc = Document(
        contract_id=contract.id if contract else None,
        client_id=(contract.client_id if contract else client.id if client else None),
        addendum_id=addendum.id if addendum else None, template_code=tpl.code, template_version=tpl.version,
        template_sha256=tpl.sha256, template_approved=composed["approved"], title=composed["title"],
        data={"params": composed["ctx"]["params"], "ctx": composed["ctx"],
              "sources": {"client_id": str(client.id) if client else None,
                          "car_id": str(car.id) if car else None}},
        checks=composed["checks"], body=composed["text"],
        body_sha256=hashlib.sha256(composed["text"].encode()).hexdigest(),
        visible_to_client=tpl.visible_to_client, created_by=user_id,
    )
    db.add(doc)
    db.flush()
    return doc


def watermark(doc: Document) -> str:
    if not doc.template_approved:
        return "ПРОЕКТ · ШАБЛОН НЕ УТВЕРЖДЁН ЮРИСТОМ"
    if doc.status in (DocumentStatus.draft, DocumentStatus.pending_approval, DocumentStatus.cancelled):
        return "ПРОЕКТ"
    return ""


def is_final(doc: Document) -> bool:
    return not watermark(doc)


def footer(doc: Document) -> str:
    return f"Islamic Car · документ {str(doc.id)[:8]} · контрольная сумма {doc.body_sha256[:12]}"


def blocks_for(doc: Document) -> list[dict]:
    return parse(doc.body, doc.data.get("ctx", {}))
