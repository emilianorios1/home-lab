"""Portable PDF text extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class ExtractedPdf:
    text: str
    page_count: int


def extract_pdf(path: Path) -> ExtractedPdf:
    reader = PdfReader(path)
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise ValueError("PDF contains no extractable text; OCR is required")
    return ExtractedPdf(text=text, page_count=len(reader.pages))
