"""Библиотеки знаний: просмотр, редакции, заключения специалистов, оценка норм."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.knowledge.service import LIBRARIES, assess, load_records, record_dict, record_review
from app.models import KnowledgeReview, User
from app.schemas import StrictModel
from app.security import Actor, require
from app.services import audit
from app.services.common import today

router = APIRouter(prefix="/api/admin/knowledge", tags=["admin: knowledge"])


class ReviewIn(StrictModel):
    version: str = Field(min_length=1, max_length=20)
    status: str = Field(pattern=r"^(approved|rejected)$")
    reviewer_name: str = Field(min_length=3, max_length=200)
    reviewer_role: str = Field(min_length=3, max_length=60)
    note: str = Field(default="", max_length=4000)


@router.get("")
def list_records(library: str | None = None, q: str = "", actor: Actor = Depends(require("knowledge.read")),
                 db: Session = Depends(get_db)):
    on = today()
    every = [record_dict(db, r, on) for r in load_records()]
    # Сводка — по всем библиотекам, независимо от фильтра списка
    summary = {lib: {"title": title, "total": sum(1 for i in every if i["library"] == lib),
                     "reliable": sum(1 for i in every if i["library"] == lib and i["reliable"])}
               for lib, title in LIBRARIES.items()}
    items = [i for i in every if not library or i["library"] == library]
    if q:
        needle = q.lower()
        items = [i for i in items
                 if needle in f"{i['title']} {i['act']} {i['article']} {i['summary']} {i['code']}".lower()]
    return {"items": items, "summary": summary}


@router.get("/assess")
def assess_codes(codes: str = Query(..., description="Коды через запятую"), on: date | None = None,
                 actor: Actor = Depends(require("knowledge.read")), db: Session = Depends(get_db)):
    return assess(db, [c.strip() for c in codes.split(",") if c.strip()], on or today())


@router.get("/{code}")
def record_history(code: str, actor: Actor = Depends(require("knowledge.read")), db: Session = Depends(get_db)):
    versions = [record_dict(db, r, today()) for r in load_records() if r.code == code]
    if not versions:
        raise HTTPException(404, "Запись не найдена")
    reviews = db.execute(select(KnowledgeReview, User.full_name).join(User, User.id == KnowledgeReview.reviewed_by)
                         .where(KnowledgeReview.code == code).order_by(KnowledgeReview.reviewed_at.desc())).all()
    return {"versions": versions, "reviews": [
        {"version": r.version, "status": r.status, "reviewer_name": r.reviewer_name, "reviewer_role": r.reviewer_role,
         "note": r.note, "recorded_by": who, "reviewed_at": r.reviewed_at, "revoked_at": r.revoked_at,
         "sha256": r.content_sha256} for r, who in reviews]}


@router.post("/{code}/review")
def review(code: str, data: ReviewIn, actor: Actor = Depends(require("knowledge.review")),
           db: Session = Depends(get_db)):
    """Фиксирует заключение специалиста. Система сама норму не утверждает."""
    try:
        r = record_review(db, code, data.version, data.status, data.reviewer_name, data.reviewer_role, data.note,
                          actor.user.id)
    except LookupError:
        raise HTTPException(404, "Запись не найдена") from None
    audit.record(db, actor, "knowledge.reviewed", "knowledge", code, version=data.version, status=data.status,
                 reviewer=data.reviewer_name, role=data.reviewer_role, sha256=r.content_sha256)
    db.commit()
    return record_history(code, actor, db)
