"""Writers for the synthetic corpus: HTML site pages, multi-page PDFs, image-only PDFs, XLSX."""

from __future__ import annotations

import html
from pathlib import Path

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

DISCLAIMER = "Fictional company created for an AI engineering assessment. Not a real insurer or lender."


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def html_page(*, brand: dict, title: str, body: str, lang: str = "en") -> str:
    """Wraps body in the site chrome (cookie banner, header, nav, aside, footer) the pipeline must strip."""
    nav = "".join(f'<li><a href="{href}">{html.escape(label)}</a></li>' for label, href in brand["nav"])
    return f"""<!doctype html>
<html lang="{lang}">
<head><meta charset="utf-8"><title>{html.escape(title)} | {html.escape(brand['name'])}</title>
<meta name="description" content="{html.escape(brand['tagline'])}"></head>
<body>
<div class="cookie-banner" id="cookie-consent">{brand['cookie']} <a href="#">Accept all</a> <a href="#">Manage preferences</a></div>
<header class="site-header">
  <a class="logo" href="{brand['home']}">{html.escape(brand['name'])}</a>
  <span class="helpline">{html.escape(brand['helpline'])}</span>
  <a href="#">Login</a> <a href="#">Pay premium</a>
</header>
<nav class="main-nav" role="navigation"><ul>{nav}</ul></nav>
<div class="breadcrumbs"><a href="{brand['home']}">Home</a> &gt; {html.escape(title)}</div>
<main>
<article>
<h1>{html.escape(title)}</h1>
{body}
</article>
</main>
<aside class="related-links"><h4>You may also like</h4><ul><li><a href="#">Download brochure</a></li>
<li><a href="#">Talk to an advisor</a></li><li><a href="#">Premium calculator</a></li></ul></aside>
<footer class="site-footer">
  <p>{html.escape(brand['footer'])}</p>
  <p>{DISCLAIMER}</p>
  <p><a href="#">Privacy policy</a> | <a href="#">Terms of use</a> | <a href="#">Sitemap</a> | <a href="#">Careers</a></p>
</footer>
</body></html>
"""


def js_only_page(*, brand: dict, title: str) -> str:
    """Content rendered client-side only: a static fetch yields no article text (expected extraction failure)."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)} | {html.escape(brand['name'])}</title></head>
<body><div id="root"></div><noscript>Please enable JavaScript to compare plans.</noscript>
<script>fetch('/api/plans').then(r=>r.json()).then(d=>{{document.getElementById('root').innerHTML=d.html}})</script>
</body></html>"""


def _styles():
    s = getSampleStyleSheet()
    return s["Title"], s["Heading2"], s["BodyText"]


def pdf_document(path: Path, *, header: str, footer: str, title: str, sections: list[tuple[str, list]]) -> None:
    """sections: [(heading, [paragraph str | ("table", rows) | ("pagebreak",)])]. Header/footer repeat per page."""
    path.parent.mkdir(parents=True, exist_ok=True)
    t_style, h_style, b_style = _styles()

    def _chrome(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(18 * mm, A4[1] - 12 * mm, header)
        canvas.drawString(18 * mm, 10 * mm, f"{footer}  |  Page {doc.page}")
        canvas.restoreState()

    story: list = [Paragraph(html.escape(title), t_style), Spacer(1, 6)]
    for heading, items in sections:
        story.append(Paragraph(html.escape(heading), h_style))
        for item in items:
            if isinstance(item, tuple) and item[0] == "table":
                tbl = Table(item[1], hAlign="LEFT")
                tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, "grey"), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
                story += [tbl, Spacer(1, 6)]
            elif isinstance(item, tuple) and item[0] == "pagebreak":
                story.append(PageBreak())
            else:
                story.append(Paragraph(html.escape(item), b_style))
        story.append(Spacer(1, 4))
    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm,
                            title=title, author="Synthetic corpus")
    doc.build(story, onFirstPage=_chrome, onLaterPages=_chrome)


def image_only_pdf(path: Path, lines: list[str]) -> None:
    """Simulates a scanned document: text drawn into a bitmap, no text layer."""
    from PIL import Image, ImageDraw
    from reportlab.pdfgen import canvas as pdf_canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("L", (1240, 1754), 255)
    draw = ImageDraw.Draw(img)
    y = 120
    for line in lines:
        draw.text((100, y), line, fill=0)
        y += 40
    png = path.with_suffix(".png")
    img.save(png)
    c = pdf_canvas.Canvas(str(path), pagesize=A4)
    c.drawImage(str(png), 0, 0, width=A4[0], height=A4[1])
    c.save()
    png.unlink()


def xlsx(path: Path, sheets: dict[str, list[list]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    wb.save(path)
