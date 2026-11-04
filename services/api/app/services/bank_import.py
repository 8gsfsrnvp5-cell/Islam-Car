"""Импорт банковских выписок в формате обмена 1C (1CClientBankExchange) и сопоставление поступлений с договорами.

Формат выгружают интернет-банки для бухгалтерских программ. Система предлагает договор для каждого поступления
и объясняет почему; платёж по договору создаётся только после подтверждения сотрудником.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BankImport, BankTransaction, Contract, ContractStatus
from app.services.contracts import get_company, ledger_for
from app.services.ledger import LedgerSummary

HEADER = "1CClientBankExchange"
AUTO_SUGGEST_SCORE = 60
CLEAR_LEAD = 20


class StatementError(ValueError):
    pass


@dataclass
class StatementDoc:
    fields: dict[str, str]

    def get(self, *names: str) -> str:
        for n in names:
            if self.fields.get(n, "").strip():
                return self.fields[n].strip()
        return ""


@dataclass
class Statement:
    account: str
    period_from: date | None
    period_to: date | None
    docs: list[StatementDoc] = field(default_factory=list)


def decode(content: bytes) -> str:
    if content.startswith(b"\xef\xbb\xbf"):
        return content[3:].decode("utf-8")
    if "Кодировка=DOS".encode("cp866") in content:
        return content.decode("cp866")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1251")


def parse_date(value: str) -> date | None:
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", value.strip())
    return date(int(m[3]), int(m[2]), int(m[1])) if m else None


def parse_amount(value: str) -> int:
    try:
        return int((Decimal(value.strip().replace(",", ".")) * 100).to_integral_value())
    except InvalidOperation:
        raise StatementError(f"Некорректная сумма: {value}") from None


def parse(content: bytes) -> Statement:
    text = decode(content)
    lines = [ln.strip() for ln in text.splitlines()]
    if not lines or lines[0] != HEADER:
        raise StatementError("Это не выписка в формате обмена 1C (первая строка должна быть «1CClientBankExchange»)")
    head: dict[str, str] = {}
    docs: list[StatementDoc] = []
    current: dict[str, str] | None = None
    for line in lines[1:]:
        if line.startswith("СекцияДокумент"):
            current = {"ВидДокумента": line.partition("=")[2]}
        elif line == "КонецДокумента":
            if current is not None:
                docs.append(StatementDoc(current))
            current = None
        elif line == "КонецФайла":
            break
        elif "=" in line:
            key, _, value = line.partition("=")
            (current if current is not None else head)[key.strip()] = value.strip()
    account = head.get("РасчСчет", "")
    return Statement(account=account, period_from=parse_date(head.get("ДатаНачала", "")),
                     period_to=parse_date(head.get("ДатаКонца", "")), docs=docs)


def payer_name(doc: StatementDoc) -> str:
    name = doc.get("Плательщик1", "Плательщик")
    return re.sub(r"^ИНН\s*\d+\s*", "", name).strip()


def incoming(statement: Statement, doc: StatementDoc, our_account: str) -> bool:
    accounts = {a for a in (statement.account, our_account) if a}
    return doc.get("ПолучательСчет") in accounts if accounts else bool(doc.get("ДатаПоступило"))


def external_key(account: str, doc: StatementDoc, amount: int) -> str:
    raw = "|".join([account, doc.get("Номер"), doc.get("Дата"), str(amount),
                    doc.get("ПлательщикИНН", "ПлательщикСчет")])
    return hashlib.sha256(raw.encode()).hexdigest()


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower().replace("ё", "е"))).strip()


def mentions(text: str, number: str) -> bool:
    n = norm(number)
    return bool(n) and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text) is not None


def score(tx: BankTransaction, c: Contract, lg: LedgerSummary) -> tuple[int, list[str]]:
    if tx.amount_kopecks > lg.outstanding_kopecks:
        return 0, ["сумма больше остатка долга"]
    points, reasons = 0, []
    if c.number and mentions(norm(tx.purpose), c.number):
        points += 60
        reasons.append(f"в назначении указан договор № {c.number}")
    client = c.client
    if client.inn and tx.payer_inn and client.inn == tx.payer_inn:
        points += 30
        reasons.append("ИНН плательщика совпадает с ИНН покупателя")
    payer, full = norm(tx.payer_name), norm(client.full_name)
    if payer and full and (payer == full or payer.startswith(full + " ") or full.startswith(payer + " ")):
        points += 25
        reasons.append("плательщик совпадает с покупателем")
    elif payer and full and payer.split(" ")[0] == full.split(" ")[0]:
        points += 10
        reasons.append("совпадает фамилия плательщика")
    if tx.amount_kopecks and tx.amount_kopecks in {lg.next_due_kopecks, lg.overdue_kopecks}:
        points += 15
        reasons.append("сумма равна очередному платежу или просрочке")
    return points, reasons


def live_contracts(db: Session) -> list[tuple[Contract, LedgerSummary]]:
    signed = db.scalars(select(Contract).where(Contract.status == ContractStatus.signed))
    return [(c, ledger_for(db, c)) for c in signed]


def match(tx: BankTransaction, contracts: list[tuple[Contract, LedgerSummary]]) -> None:
    """Предлагает договор, если лучший вариант уверенный и однозначный. Иначе — ручной выбор."""
    candidates = []
    for c, lg in contracts:
        s, reasons = score(tx, c, lg)
        if s > 0:
            candidates.append((s, c, reasons))
    candidates.sort(key=lambda x: -x[0])
    if not candidates:
        tx.status, tx.match_contract_id, tx.match_score, tx.match_reasons = "new", None, 0, ["договор не найден"]
        return
    best_score, best, reasons = candidates[0]
    second = candidates[1][0] if len(candidates) > 1 else 0
    clear = best_score >= AUTO_SUGGEST_SCORE and best_score - second >= CLEAR_LEAD
    tx.match_contract_id, tx.match_score = best.id, best_score
    tx.status = "suggested" if clear else "new"
    tx.match_reasons = reasons if clear else reasons + ["совпадение неуверенное — выберите договор вручную"]


def import_statement(db: Session, content: bytes, file_name: str, user_id) -> BankImport:
    """Сохраняет входящие поступления выписки. Платежи по договорам здесь не создаются."""
    sha = hashlib.sha256(content).hexdigest()
    if db.scalar(select(BankImport.id).where(BankImport.file_sha256 == sha)):
        raise StatementError("Эта выписка уже загружена")
    statement = parse(content)
    our_account = get_company(db).bank_account
    if statement.account and our_account and statement.account != our_account:
        raise StatementError(f"Выписка по счёту {statement.account}, а в реквизитах компании указан {our_account}")
    account = statement.account or our_account
    imp = BankImport(file_name=file_name[:200], file_sha256=sha, file_format=HEADER, account=account,
                     period_from=statement.period_from, period_to=statement.period_to,
                     rows_total=len(statement.docs), created_by=user_id)
    db.add(imp)
    db.flush()
    contracts = live_contracts(db)
    seen: set[str] = set()
    for doc in statement.docs:
        if not incoming(statement, doc, our_account):
            continue
        imp.rows_incoming += 1
        amount = parse_amount(doc.get("Сумма") or "0")
        doc_date = parse_date(doc.get("Дата"))
        received_on = parse_date(doc.get("ДатаПоступило")) or doc_date
        if amount <= 0 or doc_date is None or received_on is None:
            raise StatementError(f"В документе № {doc.get('Номер') or '?'} нет суммы или даты")
        key = external_key(account, doc, amount)
        if key in seen or db.scalar(select(BankTransaction.id).where(BankTransaction.external_key == key)):
            continue
        seen.add(key)
        inn = doc.get("ПлательщикИНН")
        tx = BankTransaction(import_id=imp.id, external_key=key, doc_number=doc.get("Номер")[:40], doc_date=doc_date,
                             received_on=received_on, amount_kopecks=amount, payer_name=payer_name(doc)[:300],
                             payer_inn="" if inn.strip("0") == "" else inn[:12],
                             payer_account=doc.get("ПлательщикСчет", "ПлательщикРасчСчет")[:20],
                             purpose=doc.get("НазначениеПлатежа"))
        match(tx, contracts)
        db.add(tx)
        imp.rows_new += 1
    db.flush()
    return imp
