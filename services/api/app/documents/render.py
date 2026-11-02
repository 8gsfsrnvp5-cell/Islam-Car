"""Экспорт блоков документа в PDF (fpdf2) и DOCX (python-docx).

Черновики и документы из неутверждённых шаблонов всегда помечаются водяным знаком.
Подписи, печати и отметки нотариуса система не создаёт — только места для них.
"""

import io
from pathlib import Path

from docx import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from fpdf import FPDF
from fpdf.fonts import FontFace

from app.config import get_settings

FONT_CANDIDATES = [
    ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
    ("arial.ttf", "arialbd.ttf"),
]
FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation"),
             Path("/usr/share/fonts/truetype/liberation2"), Path("C:/Windows/Fonts")]


class FontNotFound(RuntimeError):
    pass


def find_font() -> tuple[Path, Path]:
    dirs = ([Path(get_settings().document_font_dir)] if get_settings().document_font_dir else []) + FONT_DIRS
    for regular, bold in FONT_CANDIDATES:
        for folder in dirs:
            if (folder / regular).is_file() and (folder / bold).is_file():
                return folder / regular, folder / bold
    raise FontNotFound("Не найден шрифт с кириллицей для PDF (DejaVu Sans или Liberation Sans). "
                       "Установите fonts-dejavu-core или задайте DOCUMENT_FONT_DIR.")


class _Pdf(FPDF):
    def __init__(self, watermark: str, footer_text: str) -> None:
        super().__init__(format="A4")
        self.watermark = watermark
        self.footer_text = footer_text

    def header(self) -> None:
        if not self.watermark:
            return
        self.set_font("Doc", "B", 30)
        self.set_text_color(230, 170, 170)
        with self.rotation(35, self.w / 2, self.h / 2):
            width = self.get_string_width(self.watermark)
            self.text(self.w / 2 - width / 2, self.h / 2, self.watermark)
        self.set_text_color(0, 0, 0)
        self.set_xy(self.l_margin, self.t_margin)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Doc", "", 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, f"{self.footer_text} · стр. {self.page_no()}/{{nb}}", align="C")
        self.set_text_color(0, 0, 0)


def _keep_space(pdf: FPDF, height_mm: float) -> None:
    if pdf.get_y() + height_mm > pdf.h - pdf.b_margin:
        pdf.add_page()


def to_pdf(blocks: list[dict], watermark: str, footer_text: str) -> bytes:
    regular, bold = find_font()
    pdf = _Pdf(watermark, footer_text)
    pdf.add_font("Doc", "", str(regular))
    pdf.add_font("Doc", "B", str(bold))
    pdf.set_margins(20, 18, 15)
    pdf.set_auto_page_break(True, margin=18)
    pdf.alias_nb_pages()
    pdf.add_page()
    for b in blocks:
        t = b["type"]
        if t == "h1":
            pdf.set_font("Doc", "B", 13)
            pdf.multi_cell(0, 6.5, b["text"], align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif t == "h2":
            _keep_space(pdf, 25)  # заголовок раздела не остаётся один внизу страницы
            pdf.ln(1.5)
            pdf.set_font("Doc", "B", 10.5)
            pdf.multi_cell(0, 5.5, b["text"], new_x="LMARGIN", new_y="NEXT")
            pdf.ln(0.5)
        elif t == "p":
            pdf.set_font("Doc", "", 10)
            pdf.multi_cell(0, 5, b["text"], align="J", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)
        elif t == "note":
            pdf.set_font("Doc", "", 8)
            pdf.set_text_color(90, 90, 90)
            pdf.multi_cell(0, 4.2, b["text"], new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
        elif t == "table":
            pdf.set_font("Doc", "", 8.5)
            rows = ([b["header"]] if b.get("header") else []) + b["rows"] + ([b["footer"]] if b.get("footer") else [])
            if rows:
                with pdf.table(first_row_as_headings=bool(b.get("header")), line_height=4.6,
                               headings_style=FontFace(emphasis="BOLD", fill_color=(238, 238, 238))) as table:
                    for r in rows:
                        row = table.row()
                        for cell in r:
                            row.cell(str(cell))
            pdf.ln(3)
        elif t == "signatures":
            _keep_space(pdf, 34)  # блок подписей целиком на одной странице
            pdf.ln(4)
            pdf.set_font("Doc", "", 9.5)
            with pdf.table(borders_layout="NONE", first_row_as_headings=False, line_height=5.5) as table:
                for line in (lambda p: p["title"], lambda p: p["name"],
                             lambda p: "_________________ / подпись", lambda p: "Дата: «___» __________ 20___ г."):
                    row = table.row()
                    for party in b["parties"]:
                        row.cell(line(party))
    return bytes(pdf.output())


def to_docx(blocks: list[dict], watermark: str, footer_text: str) -> bytes:
    doc = DocxDocument()
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)
    section = doc.sections[0]
    if watermark:
        hp = section.header.paragraphs[0]
        run = hp.add_run(watermark)
        run.bold = True
        run.font.color.rgb = RGBColor(0xC0, 0x30, 0x30)
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp = section.footer.paragraphs[0]
    fr = fp.add_run(footer_text)
    fr.font.size = Pt(7)
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for b in blocks:
        t = b["type"]
        if t in ("h1", "h2"):
            p = doc.add_paragraph()
            r = p.add_run(b["text"])
            r.bold = True
            r.font.size = Pt(13 if t == "h1" else 11)
            if t == "h1":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif t == "p":
            p = doc.add_paragraph(b["text"])
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        elif t == "note":
            p = doc.add_paragraph()
            r = p.add_run(b["text"])
            r.italic = True
            r.font.size = Pt(8.5)
        elif t == "table":
            rows = ([b["header"]] if b.get("header") else []) + b["rows"] + ([b["footer"]] if b.get("footer") else [])
            if not rows:
                continue
            table = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for i, r in enumerate(rows):
                for j, cell in enumerate(r):
                    table.cell(i, j).text = str(cell)
                    if i == 0 and b.get("header"):
                        for run in table.cell(i, j).paragraphs[0].runs:
                            run.bold = True
            doc.add_paragraph()
        elif t == "signatures":
            parties = b["parties"]
            table = doc.add_table(rows=4, cols=len(parties))
            for j, party in enumerate(parties):
                lines = [party["title"], party["name"], "_________________ / подпись",
                         "Дата: «___» __________ 20___ г."]
                for i, text in enumerate(lines):
                    table.cell(i, j).text = text
                table.cell(0, j).paragraphs[0].runs[0].bold = True
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
