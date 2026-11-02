"""Простая разметка шаблонов → блоки документа (одни и те же для PDF, DOCX и предпросмотра).

  # Заголовок            ## Подзаголовок        > примечание мелким шрифтом
  | a | b |  (строка |---| после первой строки делает её шапкой таблицы)
  ::schedule:: ::ledger:: ::payments:: ::new_schedule::   — таблицы из данных договора
  ::signatures:seller,buyer::                               — места для подписей (подписи не создаются)
"""

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from app.documents.registry import LAWYER_MARK

_env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True,
                            trim_blocks=True, lstrip_blocks=True)

SIGNER_TITLES = {"seller": "Продавец", "buyer": "Покупатель", "guarantor": "Поручитель", "pledgor": "Залогодатель",
                 "pledgee": "Залогодержатель"}


def render_text(template_body: str, ctx: dict) -> str:
    return _env.from_string(template_body).render(**ctx)


def _table_from(ctx: dict, kind: str) -> dict:
    if kind == "schedule":
        rows = [[r["label"], r["date"], r["amount"]] for r in ctx.get("schedule", [])]
        return {"type": "table", "header": ["Платёж", "Срок оплаты", "Сумма"], "rows": rows,
                "footer": ["Итого", "", ctx.get("contract", {}).get("sale_price", "")]}
    if kind == "ledger":
        rows = [[r["label"], r["date"], r["amount"], r["paid"], r["remaining"], r["status"]]
                for r in ctx.get("ledger", {}).get("rows", [])]
        lg = ctx.get("ledger", {})
        return {"type": "table", "header": ["Платёж", "Срок", "По графику", "Оплачено", "Остаток", "Статус"],
                "rows": rows,
                "footer": ["Итого", "", lg.get("total", ""), lg.get("paid", ""), lg.get("outstanding", ""), ""]}
    if kind == "payments":
        rows = [[p["date"], p["amount"], p["document"]] for p in ctx.get("payments", [])]
        return {"type": "table", "header": ["Дата поступления", "Сумма", "Документ"],
                "rows": rows or [["—", "—", "платежей не поступало"]], "footer": None}
    if kind == "new_schedule":
        rows = [[r["label"], r["date"], r["amount"]] for r in ctx.get("addendum", {}).get("rows", [])]
        return {"type": "table", "header": ["Платёж", "Срок оплаты", "Сумма"], "rows": rows,
                "footer": ["Итого", "", ctx.get("contract", {}).get("sale_price", "")]}
    raise ValueError(f"Неизвестная таблица ::{kind}::")


def _signatures(ctx: dict, spec: str) -> dict:
    parties = []
    for role in spec.split(","):
        role = role.strip()
        if role in ("seller", "pledgee"):
            name = ctx.get("seller", {}).get("name", "")
        elif role in ("buyer", "pledgor"):
            name = ctx.get("client", {}).get("full_name", "")
        else:
            name = ctx.get("params", {}).get(f"{role}_name", "")
        parties.append({"title": SIGNER_TITLES.get(role, role), "name": name})
    return {"type": "signatures", "parties": parties}


def parse(text: str, ctx: dict) -> list[dict]:
    blocks: list[dict] = []
    para: list[str] = []
    table: list[list[str]] | None = None
    header: list[str] | None = None

    def flush_para() -> None:
        if para:
            blocks.append({"type": "p", "text": " ".join(s.strip() for s in para)})
            para.clear()

    def flush_table() -> None:
        nonlocal table, header
        if table is not None:
            blocks.append({"type": "table", "header": header, "rows": table, "footer": None})
        table, header = None, None

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("|"):
            flush_para()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= {"-", ":"} and c for c in cells):
                if table:
                    header = table.pop()
                continue
            table = (table or []) + [cells]
            continue
        flush_table()
        if not stripped:
            flush_para()
        elif stripped.startswith("::") and stripped.endswith("::"):
            flush_para()
            name = stripped.strip(":")
            if name.startswith("signatures"):
                blocks.append(_signatures(ctx, name.split(":", 1)[1] if ":" in name else "seller,buyer"))
            else:
                blocks.append(_table_from(ctx, name))
        elif stripped.startswith("## "):
            flush_para()
            blocks.append({"type": "h2", "text": stripped[3:]})
        elif stripped.startswith("# "):
            flush_para()
            blocks.append({"type": "h1", "text": stripped[2:]})
        elif stripped.startswith("> "):
            flush_para()
            blocks.append({"type": "note", "text": stripped[2:]})
        else:
            para.append(stripped)
    flush_para()
    flush_table()
    return blocks


def lawyer_points(text: str) -> list[str]:
    return [" ".join(m.split()) for m in LAWYER_MARK.findall(text)]
