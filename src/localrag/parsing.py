"""Tiedostojen muunto tekstiksi.

Markdown on suositeltu muoto, koska pilkkoja hyödyntää sen otsikoita.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

MARKDOWN_EXTS = {".md", ".markdown", ".mdx"}
TEXT_EXTS = {
    ".txt",
    ".rst",
    ".adoc",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".java",
    ".go",
    ".rs",
    ".sql",
    ".sh",
    ".gradle",
    ".xml",
    ".tf",
}
DOCLING_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}

Format = Literal["markdown", "text"]


@dataclass
class ParsedDocument:
    text: str
    format: Format
    parser: str


def _docling_available() -> bool:
    try:
        import docling  # noqa: F401
    except ImportError:
        return False
    return True


def is_supported(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in MARKDOWN_EXTS or ext in TEXT_EXTS or ext == ".pdf":
        return True
    return ext in DOCLING_EXTS and _docling_available()


@lru_cache(maxsize=1)
def _docling_converter():
    from docling.document_converter import DocumentConverter

    return DocumentConverter()


def _parse_docling(path: Path) -> ParsedDocument:
    result = _docling_converter().convert(str(path))
    return ParsedDocument(result.document.export_to_markdown(), "markdown", "docling")


def _parse_pdf_pypdf(path: Path) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            # Sivuotsikot päätyvät otsikkopolkuun, jolloin agentti voi viitata sivunumeroon.
            parts.append(f"# Page {i}\n\n{text}")
    return ParsedDocument("\n\n".join(parts), "markdown", "pypdf")


def parse(path: Path) -> ParsedDocument | None:
    ext = path.suffix.lower()
    if ext in MARKDOWN_EXTS:
        return ParsedDocument(
            path.read_text(encoding="utf-8", errors="replace"), "markdown", "text"
        )
    if ext in TEXT_EXTS:
        return ParsedDocument(path.read_text(encoding="utf-8", errors="replace"), "text", "text")
    if ext in DOCLING_EXTS and _docling_available():
        return _parse_docling(path)
    if ext == ".pdf":
        return _parse_pdf_pypdf(path)
    log.debug("Unsupported file type: %s", path)
    return None
