"""Generoi demon PDF-tiedostot hakemistosta examples/pdf-sources hakemistoon examples/docs.

Lähteet ovat yksinkertaista markdownia: '#' ja '##' otsikoille, '- ' luettelolle,
tyhjä rivi kappaleiden välissä ja '<!-- pagebreak -->' sivunvaihdolle.

Ajo: uv run python scripts/generate_example_pdfs.py
"""

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab import rl_config
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate

# Sama sisältö tuottaa tavulleen saman PDF:n (ei aikaleimoja), jolloin git-diffit pysyvät siisteinä.
rl_config.invariant = 1

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "examples" / "pdf-sources"
OUTPUT = ROOT / "examples" / "docs"


def build_flowables(markdown: str) -> list:
    styles = getSampleStyleSheet()
    flowables: list = []
    bullets: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            flowables.append(Paragraph(escape(" ".join(paragraph)), styles["BodyText"]))
            paragraph.clear()

    def flush_bullets() -> None:
        if bullets:
            items = [ListItem(Paragraph(escape(b), styles["BodyText"])) for b in bullets]
            flowables.append(ListFlowable(items, bulletType="bullet", leftIndent=12))
            bullets.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped == "<!-- pagebreak -->":
            flush_paragraph()
            flush_bullets()
            flowables.append(PageBreak())
        elif stripped.startswith("## "):
            flush_paragraph()
            flush_bullets()
            flowables.append(Paragraph(escape(stripped[3:]), styles["Heading2"]))
        elif stripped.startswith("# "):
            flush_paragraph()
            flush_bullets()
            flowables.append(Paragraph(escape(stripped[2:]), styles["Title"]))
        elif stripped.startswith("- "):
            flush_paragraph()
            bullets.append(stripped[2:])
        elif not stripped:
            flush_paragraph()
            flush_bullets()
        else:
            paragraph.append(stripped)
    flush_paragraph()
    flush_bullets()
    return flowables


def main() -> None:
    for source in sorted(SOURCES.glob("*.md")):
        target = OUTPUT / f"{source.stem}.pdf"
        text = source.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        doc = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            leftMargin=2.5 * cm,
            rightMargin=2.5 * cm,
            title=title,
            author="Lumikko Demo Oy (kuvitteellinen)",
        )
        doc.build(build_flowables(text))
        print(f"{source.relative_to(ROOT)} -> {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
