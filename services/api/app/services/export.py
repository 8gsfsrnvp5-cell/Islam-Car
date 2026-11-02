"""Выгрузки для Excel: CSV (открывается в русском Excel) и XLSX с числами, датами и форматами."""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime

from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str) -> str:
    """Защита от формул в ячейках: текст из карточек и выписок не должен исполняться в Excel."""
    if value.startswith(FORMULA_START) and not _is_number(value):
        return "'" + value
    return value


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", ".").replace(" ", ""))
        return True
    except ValueError:
        return False


def csv_response(rows: list[list[str]], filename: str) -> Response:
    buf = io.StringIO()
    csv.writer(buf, delimiter=";").writerows([[safe_text(str(v)) for v in row] for row in rows])
    # BOM — чтобы Excel определил кодировку UTF-8
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def money(kopecks: int) -> str:
    rubles, kop = divmod(kopecks, 100)
    return f"{rubles},{kop:02d}"


@dataclass(frozen=True)
class Money:
    kopecks: int


@dataclass(frozen=True)
class Percent:
    value: float | None


@dataclass
class Sheet:
    title: str
    header: list[str]
    rows: list[list] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _write(ws, row: int, col: int, value) -> int:
    cell = ws.cell(row=row, column=col)
    if isinstance(value, Money):
        cell.value = value.kopecks / 100
        cell.number_format = "#,##0.00"
        return 14
    if isinstance(value, Percent):
        cell.value = None if value.value is None else value.value / 100
        cell.number_format = "0.0%"
        return 8
    if isinstance(value, datetime | date):
        cell.value = value
        cell.number_format = "DD.MM.YYYY HH:MM" if isinstance(value, datetime) else "DD.MM.YYYY"
        return 12
    if isinstance(value, str):
        cell.value = value
        cell.data_type = "s"  # строка, даже если начинается с «=»: формулы из данных не исполняются
        return min(max(len(value), 6), 60)
    cell.value = value
    return 8


def xlsx_response(sheets: list[Sheet], filename: str) -> Response:
    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="E8EEF4")
    for sheet in sheets:
        ws = wb.create_sheet(sheet.title[:31])
        widths: dict[int, int] = {}
        for col, title in enumerate(sheet.header, start=1):
            c = ws.cell(row=1, column=col, value=title)
            c.font, c.fill = Font(bold=True), head_fill
            c.alignment = Alignment(wrap_text=True, vertical="top")
            widths[col] = min(max(len(title), 8), 40)
        for r, values in enumerate(sheet.rows, start=2):
            for col, value in enumerate(values, start=1):
                widths[col] = max(widths.get(col, 8), _write(ws, r, col, value))
        for i, note in enumerate(sheet.notes):
            ws.cell(row=len(sheet.rows) + 3 + i, column=1, value=note).font = Font(italic=True, color="555555")
        for col, w in widths.items():
            ws.column_dimensions[get_column_letter(col)].width = w + 2
        ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type=XLSX_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
