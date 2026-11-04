"""Автоматическая проверка документов: актуальность, комплектность, целостность, согласованность с договором.

Проверка ничего не исправляет и не подписывает — она показывает, что нужно сделать сотруднику или юристу.
Перечень ожидаемых документов — внутренний порядок компании по её шаблонам; его подтверждает юрист.
"""

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.documents import registry
from app.documents.context import build_context, money
from app.models import Addendum, Car, Client, Contract, ContractStatus, Document, DocumentStatus

# Разделы контекста, которые меняются сами по себе (остаток на дату, платежи) — не признак устаревания
VOLATILE = {"today", "params", "ledger", "payments"}
VOLATILE_CONTRACT = {"status", "signed_at"}
ACTIVE = (DocumentStatus.draft, DocumentStatus.pending_approval, DocumentStatus.approved)
EXPECTED = {
    ContractStatus.signed: [("sale_contract", "signed"), ("payment_schedule", "signed"), ("acceptance_act", "signed")],
    ContractStatus.completed: [("sale_contract", "signed"), ("payment_schedule", "signed"),
                               ("acceptance_act", "signed"), ("completion_confirmation", "approved")],
}
EXPECTED_NOTE = "Перечень ожидаемых документов — внутренний порядок по шаблонам компании, его подтверждает юрист."
STATUS_ORDER = {DocumentStatus.draft: 0, DocumentStatus.pending_approval: 1, DocumentStatus.approved: 2,
                DocumentStatus.signed: 3}


@dataclass
class Issue:
    severity: str  # critical | warning | info
    code: str
    title: str
    message: str
    action: str
    document_id: str | None = None
    contract_id: str | None = None
    contract_number: str | None = None


def _plain(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def comparable(ctx: dict) -> dict:
    out = {k: v for k, v in ctx.items() if k not in VOLATILE}
    if isinstance(out.get("contract"), dict):
        out["contract"] = {k: v for k, v in out["contract"].items() if k not in VOLATILE_CONTRACT}
    return _plain(out)


def changed_sections(stored: dict, fresh: dict) -> list[str]:
    a, b = comparable(stored), comparable(fresh)
    titles = {"seller": "реквизиты продавца", "contract": "условия договора", "schedule": "график",
              "client": "данные покупателя", "car": "данные автомобиля", "addendum": "дополнительное соглашение"}
    return [titles.get(k, k) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


def fresh_context(db: Session, doc: Document, on: date) -> dict:
    contract = db.get(Contract, doc.contract_id) if doc.contract_id else None
    sources = (doc.data or {}).get("sources", {})
    client = db.get(Client, uuid.UUID(sources["client_id"])) if sources.get("client_id") else None
    car = db.get(Car, uuid.UUID(sources["car_id"])) if sources.get("car_id") else None
    addendum = db.get(Addendum, doc.addendum_id) if doc.addendum_id else None
    return build_context(db, contract=contract, client=client, car=car, addendum=addendum,
                         params=(doc.data or {}).get("params", {}), today=on)


def file_sha256(name: str) -> str | None:
    path = get_settings().storage_dir / "documents" / name
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_documents(db: Session, on: date, contract_id: uuid.UUID | None = None) -> dict:
    stmt = select(Document).order_by(Document.created_at)
    if contract_id:
        stmt = stmt.where(Document.contract_id == contract_id)
    docs = list(db.scalars(stmt))
    numbers = {c.id: c for c in db.scalars(select(Contract).where(Contract.id.in_(
        {d.contract_id for d in docs if d.contract_id} | ({contract_id} if contract_id else set()))))}
    issues: list[Issue] = []

    def add(sev, code, title, message, action, doc: Document | None = None, contract: Contract | None = None):
        c = contract or (numbers.get(doc.contract_id) if doc and doc.contract_id else None)
        issues.append(Issue(sev, code, title, message, action, str(doc.id) if doc else None,
                            str(c.id) if c else None, c.number if c else None))

    for doc in docs:
        contract = numbers.get(doc.contract_id) if doc.contract_id else None
        # Целостность текста: запись в базе не менялась после формирования
        if hashlib.sha256(doc.body.encode()).hexdigest() != doc.body_sha256:
            add("critical", "body_tampered", f"«{doc.title}»: текст не совпадает с контрольной суммой",
                "Текст документа изменён в обход системы.", "Сверьте с бумажным экземпляром и журналом действий", doc)
        if doc.status == DocumentStatus.signed:
            if not doc.template_approved:
                add("critical", "signed_unapproved", f"«{doc.title}» подписан из неутверждённого шаблона",
                    "Подписанный документ создан из шаблона без утверждения юриста.", "Передайте юристу", doc)
            if doc.signed_file_name:
                actual = file_sha256(doc.signed_file_name)
                if actual is None:
                    add("critical", "scan_missing", f"«{doc.title}»: скан подписанного экземпляра не найден",
                        "Файл отсутствует в хранилище.", "Восстановите файл из резервной копии", doc)
                elif actual != doc.signed_file_sha256:
                    add("critical", "scan_changed", f"«{doc.title}»: скан изменён после загрузки",
                        "Контрольная сумма файла не совпадает с сохранённой при подписании.",
                        "Восстановите файл из резервной копии и проверьте журнал", doc)
            else:
                add("info", "scan_absent", f"«{doc.title}»: скан подписанного экземпляра не загружен",
                    "Подписание отмечено без скана.", "Загрузите скан, если он есть", doc)
            # Цена подписанного договора неизменна
            if doc.template_code == "sale_contract" and contract is not None:
                signed_price = ((doc.data or {}).get("ctx", {}).get("contract") or {}).get("sale_price")
                if signed_price and signed_price != money(contract.sale_price_kopecks):
                    add("critical", "price_mismatch", f"Договор № {contract.number}: цена отличается от подписанной",
                        f"В подписанном документе {signed_price} ₽, в карточке {money(contract.sale_price_kopecks)} ₽.",
                        "Цена договора мурабахи после подписания не меняется — проверьте карточку", doc)
            continue
        if doc.status not in ACTIVE:
            continue
        if contract is not None and contract.status == ContractStatus.cancelled:
            add("warning", "contract_cancelled", f"«{doc.title}»: договор отменён, документ не отменён",
                "Проект остался действующим после отмены договора.", "Отмените документ", doc)
            continue
        tpl = registry.get_template(doc.template_code)
        if tpl is None:
            add("warning", "template_missing", f"«{doc.title}»: шаблон больше не существует",
                "Документ создан из шаблона, которого нет в каталоге.", "Отмените документ и создайте новый", doc)
            continue
        if tpl.sha256 != doc.template_sha256:
            changed = (f"Документ создан по версии {doc.template_version}, текущая — {tpl.version}."
                       if tpl.version != doc.template_version else
                       f"Номер версии тот же ({tpl.version}), но текст или параметры шаблона изменились.")
            add("warning", "template_changed", f"«{doc.title}»: шаблон изменён после формирования", changed,
                "Сформируйте документ заново по действующему шаблону", doc)
        try:
            sections = changed_sections((doc.data or {}).get("ctx", {}), fresh_context(db, doc, on))
        except Exception as e:  # noqa: BLE001 — сбой проверки одного документа не прерывает проверку остальных
            add("warning", "check_failed", f"«{doc.title}»: не удалось проверить актуальность", str(e)[:300],
                "Откройте документ и проверьте вручную", doc)
            continue
        if sections:
            add("warning", "stale", f"«{doc.title}»: данные изменились после формирования",
                "Изменились: " + ", ".join(sections) + ".",
                "Пересоберите черновик или отмените документ и создайте новый", doc)

    # Комплектность по действующим и исполненным договорам
    contracts = [numbers[contract_id]] if contract_id and contract_id in numbers else list(db.scalars(
        select(Contract).where(Contract.status.in_(list(EXPECTED)))))
    for c in contracts:
        best: dict[str, DocumentStatus] = {}
        for d in docs:
            if d.contract_id == c.id and d.status in STATUS_ORDER:
                if STATUS_ORDER[d.status] > STATUS_ORDER.get(best.get(d.template_code), -1):
                    best[d.template_code] = d.status
        for code, needed in EXPECTED.get(c.status, []):
            have = best.get(code)
            tpl = registry.get_template(code)
            title = tpl.title if tpl else code
            if have is None:
                add("warning", "missing", f"Договор № {c.number}: нет документа «{title}»",
                    "Документ не сформирован в системе.", "Сформируйте документ или отметьте бумажный экземпляр",
                    contract=c)
            elif STATUS_ORDER[have] < STATUS_ORDER[DocumentStatus(needed)]:
                state = "подписан" if needed == "signed" else "утверждён"
                add("info", "not_final", f"Договор № {c.number}: «{title}» ещё не {state}",
                    "Документ есть, но не доведён до нужного статуса.", "Доведите документ до конца", contract=c)

    order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (order[i.severity], i.contract_number or "", i.title))
    return {"checked_documents": len(docs), "checked_contracts": len(contracts),
            "counts": {s: sum(1 for i in issues if i.severity == s) for s in order},
            "issues": [asdict(i) for i in issues], "note": EXPECTED_NOTE}
