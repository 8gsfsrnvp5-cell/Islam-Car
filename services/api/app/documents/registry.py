"""Реестр шаблонов документов из каталога templates/contracts.

Шаблон — папка с meta.json и template.md. Утверждение юристом привязано к sha256 содержимого:
любое изменение файла делает утверждение недействительным.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TemplateApproval

# Места, где юрист должен принять решение. Шаблон с такими пометками утвердить нельзя.
LAWYER_MARK = re.compile(r"\[\[ЮРИСТ:\s*(.+?)\]\]", re.S)


@dataclass
class Template:
    code: str
    title: str
    version: str
    scope: str  # contract | client | car
    description: str
    body: str
    sha256: str
    requires: list[str] = field(default_factory=list)
    requires_signed_contract: bool = False
    visible_to_client: bool = False
    params: list[dict] = field(default_factory=list)
    legal_refs: list[str] = field(default_factory=list)

    @property
    def lawyer_points(self) -> list[str]:
        return [" ".join(m.split()) for m in LAWYER_MARK.findall(self.body)]


def templates_dir() -> Path:
    return Path(get_settings().templates_dir)


def load_templates() -> dict[str, Template]:
    result: dict[str, Template] = {}
    root = templates_dir()
    if not root.is_dir():
        return result
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        meta_path, body_path = folder / "meta.json", folder / "template.md"
        if not meta_path.is_file() or not body_path.is_file():
            continue
        meta_raw = meta_path.read_bytes()
        body_raw = body_path.read_bytes()
        meta = json.loads(meta_raw.decode("utf-8"))
        result[meta["code"]] = Template(
            code=meta["code"], title=meta["title"], version=str(meta["version"]), scope=meta.get("scope", "contract"),
            description=meta.get("description", ""), body=body_raw.decode("utf-8"),
            sha256=hashlib.sha256(meta_raw + b"\0" + body_raw).hexdigest(),
            requires=meta.get("requires", []), requires_signed_contract=meta.get("requires_signed_contract", False),
            visible_to_client=meta.get("visible_to_client", False), params=meta.get("params", []),
            legal_refs=meta.get("legal_refs", []),
        )
    return result


def get_template(code: str) -> Template | None:
    return load_templates().get(code)


def active_approval(db: Session, tpl: Template) -> TemplateApproval | None:
    return db.scalar(select(TemplateApproval).where(
        TemplateApproval.template_code == tpl.code, TemplateApproval.content_sha256 == tpl.sha256,
        TemplateApproval.revoked_at.is_(None)).order_by(TemplateApproval.approved_at.desc()).limit(1))
