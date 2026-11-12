"""Builds FREELANCE_STARTER_KIT.pdf from FREELANCE_STARTER_KIT.md (simple Markdown: headings, bullets, quotes,
tables, bold/italic/code).  Run: python docs/freelance/make_pdf.py   (needs: pip install reportlab)"""

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).resolve().parent
SRC, OUT = HERE / "FREELANCE_STARTER_KIT.md", HERE / "FREELANCE_STARTER_KIT.pdf"
F, FB, FM = "Helvetica", "Helvetica-Bold", "Courier"
for d in (Path("/usr/share/fonts/truetype/dejavu"), Path(r"C:\Windows\Fonts")):
    if (d / "DejaVuSans.ttf").exists():
        pdfmetrics.registerFont(TTFont("DV", str(d / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DVB", str(d / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("DVM", str(d / "DejaVuSansMono.ttf")))
        pdfmetrics.registerFontFamily("DV", normal="DV", bold="DVB", italic="DV", boldItalic="DVB")
        F, FB, FM = "DV", "DVB", "DVM"
        break
NAVY, BLUE = colors.HexColor("#1a2340"), colors.HexColor("#2962ff")
ST = {
    "h1": ParagraphStyle("h1", fontName=FB, fontSize=18, leading=23, textColor=NAVY, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName=FB, fontSize=14, leading=18, textColor=NAVY, spaceBefore=12, spaceAfter=5),
    "h3": ParagraphStyle("h3", fontName=FB, fontSize=11.5, leading=15, textColor=BLUE, spaceBefore=8, spaceAfter=3),
    "p": ParagraphStyle("p", fontName=F, fontSize=9.5, leading=13.3, spaceAfter=4),
    "li": ParagraphStyle("li", fontName=F, fontSize=9.5, leading=13.3, leftIndent=13, bulletIndent=3, spaceAfter=2),
    "q": ParagraphStyle("q", fontName=F, fontSize=9.3, leading=13, spaceAfter=1),
    "qli": ParagraphStyle("qli", fontName=F, fontSize=9.3, leading=13, leftIndent=12, bulletIndent=2),
    "cell": ParagraphStyle("cell", fontName=F, fontSize=8.5, leading=11),
    "cellb": ParagraphStyle("cellb", fontName=FB, fontSize=8.5, leading=11, textColor=colors.white),
}


def inline(t: str) -> str:
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    return re.sub(r"`(.+?)`", rf'<font name="{FM}">\1</font>', t)


def quote_box(lines):
    """Join wrapped lines: a paragraph runs until a blank line or a list item; a list item takes its indented tail."""
    merged: list = []
    for ln in lines:
        if not ln.strip():
            merged.append("")
        elif re.match(r"^(- |\d+\. )", ln) or not merged or not merged[-1]:
            merged.append(ln)
        elif ln.startswith("  ") or not re.match(r"^(- |\d+\. )", merged[-1]):
            merged[-1] += " " + ln.strip()
        else:
            merged.append(ln)
    flow = []
    for ln in merged:
        if not ln.strip():
            flow.append(Spacer(1, 3))
        elif re.match(r"^(- |\d+\. )", ln):
            m = re.match(r"^(- |(\d+)\. )(.*)$", ln)
            flow.append(Paragraph(inline(m.group(3)), ST["qli"], bulletText="•" if m.group(1) == "- " else m.group(2) + "."))
        else:
            flow.append(Paragraph(inline(ln), ST["q"]))
    t = Table([[flow]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, BLUE), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f8ff")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return [t, Spacer(1, 6)]


def md_table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not re.match(r"^\|[\s:|-]+\|$", r.strip())]
    n = max(len(r) for r in cells)
    data = [[Paragraph(inline(c), ST["cellb" if i == 0 else "cell"]) for c in r + [""] * (n - len(r))] for i, r in enumerate(cells)]
    t = Table(data, colWidths=[174 * mm / n] * n, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9ced8")),
                           ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return [t, Spacer(1, 6)]


def build():
    lines = SRC.read_text(encoding="utf-8").splitlines()
    story, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("> ") or ln == ">":
            block = []
            while i < len(lines) and (lines[i].startswith(">")):
                block.append(lines[i][2:] if lines[i].startswith("> ") else "")
                i += 1
            story += quote_box(block)
            continue
        if ln.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            story += md_table(block)
            continue
        if ln.startswith("### "):
            story.append(Paragraph(inline(ln[4:]), ST["h3"]))
        elif ln.startswith("## "):
            story.append(Paragraph(inline(ln[3:]), ST["h2"]))
        elif ln.startswith("# "):
            story.append(Paragraph(inline(ln[2:]), ST["h1"]))
        elif ln.strip() == "---":
            story.append(HRFlowable(width="100%", color=colors.HexColor("#c9ced8"), spaceBefore=4, spaceAfter=4))
        elif re.match(r"^\s*- ", ln):
            text = re.sub(r"^\s*- ", "", ln)
            while i + 1 < len(lines) and lines[i + 1].startswith("  ") and not lines[i + 1].strip().startswith("- "):
                i += 1
                text += " " + lines[i].strip()
            indent = 26 if ln.startswith("  ") else 13
            story.append(Paragraph(inline(text), ParagraphStyle("x", parent=ST["li"], leftIndent=indent, bulletIndent=indent - 10), bulletText="•"))
        elif re.match(r"^\d+\. ", ln):
            m = re.match(r"^(\d+)\. (.*)$", ln)
            text = m.group(2)
            while i + 1 < len(lines) and lines[i + 1].startswith("   "):
                i += 1
                text += " " + lines[i].strip()
            story.append(Paragraph(inline(text), ST["li"], bulletText=m.group(1) + "."))
        elif ln.strip():
            text = ln
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(#|>|\||- |\d+\. |---)", lines[i + 1]):
                i += 1
                text += " " + lines[i]
            story.append(Paragraph(inline(text), ST["p"]))
        i += 1

    def footer(c, d):
        c.saveState()
        c.setFont(F, 7.5)
        c.setFillColor(colors.HexColor("#5f6573"))
        c.drawString(18 * mm, 9 * mm, "Freelance Starter Kit - Kunal - 12 Nov 2026")
        c.drawRightString(A4[0] - 18 * mm, 9 * mm, f"page {d.page}")
        c.restoreState()

    SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm,
                      bottomMargin=16 * mm, title="Freelance Starter Kit").build(story, onFirstPage=footer, onLaterPages=footer)
    return OUT


if __name__ == "__main__":
    print(build())
