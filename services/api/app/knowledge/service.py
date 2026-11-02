"""Библиотеки знаний: юридическая, бухгалтерская, исламского финансирования.

Записи хранятся в репозитории (knowledge/<library>/records.json), заключения специалистов — в базе
и привязаны к sha256 содержимого записи. Система не выдаёт норму за проверенную, если:
нет заключения специалиста, не заполнены даты действия, проверка устарела или норма утратила силу.
В этих случаях результат — «Требуется проверка» соответствующего специалиста.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import KnowledgeReview

LIBRARIES = {"legal": "Юридическая", "accounting": "Бухгалтерская и налоговая",
             "islamic-finance": "Исламское финансирование"}
REVIEWER = {"legal": "юриста", "accounting": "бухгалтера", "islamic-finance": "специалиста по шариату"}
GENERIC_SOURCES = {"http://pravo.gov.ru/", "https://pravo.gov.ru/", "https://aaoifi.com/", "http://aaoifi.com/"}


@dataclass
class Record:
    library: str
    code: str
    version: str
    title: str
    act: str
    article: str
    summary: str
    source_url: str
    source_hint: str
    topics: list[str]
    scope: list[str]
    effective_from: date | None
    effective_to: date | None
    last_checked: date | None
    check: str | None
    sha256: str
    raw: dict = field(repr=False, default_factory=dict)


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def load_records() -> list[Record]:
    root = Path(get_settings().knowledge_dir)
    result: list[Record] = []
    for library in LIBRARIES:
        path = root / library / "records.json"
        if not path.is_file():
            continue
        for raw in json.loads(path.read_text(encoding="utf-8"))["records"]:
            canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
            result.append(Record(
                library=library, code=raw["code"], version=str(raw.get("version", "1")), title=raw["title"],
                act=raw.get("act", ""), article=raw.get("article", ""), summary=raw.get("summary", ""),
                source_url=raw.get("source_url", ""), source_hint=raw.get("source_hint", ""),
                topics=raw.get("topics", []), scope=raw.get("scope", []),
                effective_from=_d(raw.get("effective_from")), effective_to=_d(raw.get("effective_to")),
                last_checked=_d(raw.get("last_checked")), check=raw.get("check"),
                sha256=hashlib.sha256(canonical).hexdigest(), raw=raw))
    return result


def review_for(db: Session, rec: Record) -> KnowledgeReview | None:
    return db.scalar(select(KnowledgeReview).where(
        KnowledgeReview.code == rec.code, KnowledgeReview.version == rec.version,
        KnowledgeReview.content_sha256 == rec.sha256, KnowledgeReview.revoked_at.is_(None))
        .order_by(KnowledgeReview.reviewed_at.desc()).limit(1))


def problems(rec: Record, review: KnowledgeReview | None, on: date) -> list[str]:
    """Почему на запись нельзя полностью полагаться. Пустой список — запись надёжна."""
    issues: list[str] = []
    if review is None:
        issues.append(f"не проверено — нет заключения {REVIEWER[rec.library]}")
    elif review.status != "approved":
        issues.append(f"отклонено специалистом: {review.note or 'без комментария'}")
    if rec.library != "islamic-finance" and rec.effective_from is None:
        issues.append("не заполнена дата вступления в силу")
    if rec.effective_to and rec.effective_to <= on:
        issues.append(f"утратила силу {rec.effective_to:%d.%m.%Y}")
    if rec.last_checked is None:
        issues.append("актуальность по официальной публикации не сверялась")
    elif on - rec.last_checked > timedelta(days=get_settings().knowledge_stale_days):
        issues.append(f"последняя сверка {rec.last_checked:%d.%m.%Y} — устарела")
    if rec.source_url.strip() in GENERIC_SOURCES or not rec.source_url:
        issues.append("нет точной ссылки на официальную публикацию")
    return issues


def record_dict(db: Session, rec: Record, on: date) -> dict:
    review = review_for(db, rec)
    issues = problems(rec, review, on)
    return {
        "library": rec.library, "code": rec.code, "version": rec.version, "title": rec.title, "act": rec.act,
        "article": rec.article, "summary": rec.summary, "source_url": rec.source_url, "source_hint": rec.source_hint,
        "topics": rec.topics, "scope": rec.scope, "effective_from": rec.effective_from,
        "effective_to": rec.effective_to, "last_checked": rec.last_checked, "check": rec.check, "sha256": rec.sha256,
        "review": {"status": review.status, "reviewer_name": review.reviewer_name,
                   "reviewer_role": review.reviewer_role,
                   "note": review.note, "reviewed_at": review.reviewed_at} if review else None,
        "problems": issues, "reliable": not issues,
    }


def edition_for(records: list[Record], code: str, on: date) -> tuple[Record | None, str | None]:
    """Редакция, действовавшая на дату (например, на дату договора). Второй элемент — пояснение, если выбрать нельзя."""
    versions = [r for r in records if r.code == code]
    if not versions:
        return None, "запись не найдена в библиотеке"
    dated = [r for r in versions if r.effective_from is not None]
    valid = [r for r in dated if r.effective_from <= on and (r.effective_to is None or r.effective_to > on)]
    if valid:
        return max(valid, key=lambda r: r.effective_from), None
    if dated:
        return None, f"нет редакции, действовавшей на {on:%d.%m.%Y}"
    latest = max(versions, key=lambda r: r.version)
    return latest, "даты действия не заполнены — редакция на дату не определена"


def assess(db: Session, codes: list[str], on: date) -> dict:
    """Проверка набора норм для документа или расчёта: источники, редакции, статус проверки."""
    records = load_records()
    items = []
    for code in codes:
        rec, note = edition_for(records, code, on)
        if rec is None:
            items.append({"code": code, "title": code, "reliable": False, "problems": [note], "library": None})
            continue
        data = record_dict(db, rec, on)
        if note:
            data["problems"] = [note] + data["problems"]
            data["reliable"] = False
        items.append(data)
    unreliable = [i for i in items if not i["reliable"]]
    reviewers = sorted({REVIEWER[i["library"]] for i in unreliable if i.get("library")})
    verdict = ("Все применимые нормы проверены специалистами и актуальны" if not unreliable
               else "Требуется проверка " + ", ".join(reviewers or ["юриста"]))
    return {"on": on, "items": items, "reliable": not unreliable, "verdict": verdict,
            "unreliable_count": len(unreliable)}


def record_review(db: Session, code: str, version: str, status: str, reviewer_name: str, reviewer_role: str,
                  note: str, user_id) -> KnowledgeReview:
    rec = next((r for r in load_records() if r.code == code and r.version == version), None)
    if rec is None:
        raise LookupError("Запись не найдена")
    for old in db.scalars(select(KnowledgeReview).where(KnowledgeReview.code == code,
                                                        KnowledgeReview.revoked_at.is_(None))):
        old.revoked_at = datetime.now(UTC)
    review = KnowledgeReview(code=code, version=version, content_sha256=rec.sha256, status=status,
                             reviewer_name=reviewer_name, reviewer_role=reviewer_role, note=note, reviewed_by=user_id)
    db.add(review)
    db.flush()
    return review
