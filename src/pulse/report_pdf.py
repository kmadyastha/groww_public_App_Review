"""Formatted weekly pulse PDF. Isolated from Gmail/OAuth."""

from __future__ import annotations

from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

MINT = (18, 201, 152)
INK = (22, 28, 27)
MUTED = (90, 102, 98)
LINE = (220, 228, 224)
LEFT = 14
CONTENT_W = 182


def _txt(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u2014", "-")
        .replace("\u2013", "-")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


class PulsePDF(FPDF):
    def header(self) -> None:
        self.set_fill_color(*MINT)
        self.rect(0, 0, 210, 12, "F")
        self.set_xy(LEFT, 3.5)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(255, 255, 255)
        self.cell(
            CONTENT_W,
            6,
            "Groww  |  App Review Insights Analyser",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.ln(8)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(*LINE)
        self.line(LEFT, self.get_y(), LEFT + CONTENT_W, self.get_y())
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(CONTENT_W, 8, f"Strictly confidential  ·  page {self.page_no()}", align="R")


def _section(pdf: PulsePDF, title: str) -> None:
    pdf.set_x(LEFT)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*MINT)
    pdf.cell(CONTENT_W, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _body(pdf: PulsePDF, text: str, *, italic: bool = False, size: int = 10) -> None:
    pdf.set_x(LEFT)
    pdf.set_font("Helvetica", "I" if italic else "", size)
    pdf.set_text_color(*INK)
    pdf.multi_cell(CONTENT_W, 5.5, _txt(text))
    pdf.ln(1)


def render_pulse_pdf(data: dict[str, Any]) -> bytes:
    overview = data.get("overview") or {}
    pulse = data.get("pulse") or {}
    window = data.get("window") or {}
    pdf = PulsePDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_left_margin(LEFT)
    pdf.set_right_margin(14)
    pdf.add_page()

    pdf.set_x(LEFT)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*INK)
    pdf.multi_cell(CONTENT_W, 8, _txt(pulse.get("title") or "Groww Weekly Review Pulse"))
    pdf.set_x(LEFT)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        CONTENT_W,
        6,
        _txt(
            f"Last {data.get('weeks')} weeks  ·  {window.get('start')} to {window.get('end')}  ·  "
            f"{data.get('iso_week')} / {data.get('year')}"
        ),
    )
    pdf.ln(3)

    kpis = [
        ("Reviews", f"{int(overview.get('total_reviews') or 0):,}"),
        ("Avg rating", f"{overview.get('avg_rating', 0)} / 5"),
        (
            "Sentiment",
            " / ".join(
                f"{(overview.get('sentiment') or {}).get(k, 0)} {k[:3]}."
                for k in ("positive", "negative", "neutral")
            ),
        ),
    ]
    y0 = pdf.get_y()
    col_w = 60
    for i, (label, value) in enumerate(kpis):
        x = LEFT + i * col_w
        pdf.set_fill_color(245, 250, 248)
        pdf.set_draw_color(*LINE)
        pdf.rect(x, y0, col_w - 3, 16, "DF")
        pdf.set_xy(x + 2, y0 + 1.5)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(col_w - 7, 5, _txt(label))
        pdf.set_xy(x + 2, y0 + 7)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*INK)
        pdf.cell(col_w - 7, 7, _txt(value))
    pdf.set_y(y0 + 20)

    _section(pdf, "EXECUTIVE SUMMARY")
    _body(pdf, pulse.get("executive_summary") or "")

    _section(pdf, "TOP THEMES & VERBATIM QUOTES")
    for index, row in enumerate(pulse.get("themes") or [], start=1):
        sentiment = _txt(row.get("sentiment") or "").upper()
        pdf.set_x(LEFT)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*INK)
        pdf.multi_cell(CONTENT_W, 6, _txt(f"{index:02d}  {row.get('theme', '')}   [{sentiment}]"))
        _body(pdf, f'"{row.get("quote", "")}"', italic=True)

    _section(pdf, "THREE ACTION IDEAS")
    for idea in pulse.get("actions") or []:
        pdf.set_x(LEFT)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*INK)
        pdf.multi_cell(
            CONTENT_W,
            5.5,
            _txt(f"{idea.get('title', '')}  ({idea.get('owner_hint', '')})"),
        )
        _body(pdf, idea.get("rationale") or "")

    dist = overview.get("rating_distribution") or {}
    _section(pdf, "RATING DISTRIBUTION")
    parts = [f"{star}* : {dist.get(str(star), 0)}" for star in range(5, 0, -1)]
    _body(pdf, "    |    ".join(parts))

    return bytes(pdf.output())
