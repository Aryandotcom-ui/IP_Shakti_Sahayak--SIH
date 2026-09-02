"""PDF text extraction with PyMuPDF.

Two jobs beyond "get the text out":

1.  Refuse scanned PDFs loudly rather than emitting 40 chunks of noise
    into the corpus. A silent bad ingest is far more expensive than a
    failed one, because nobody notices until the assistant cites it.
2.  Strip running headers and footers before sectioning. Gazette PDFs
    repeat "THE GAZETTE OF INDIA EXTRAORDINARY" on every page, and those
    lines otherwise land inside section bodies and pollute embeddings.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf  # PyMuPDF

log = logging.getLogger(__name__)

# A text-layer page in a statute PDF carries hundreds of characters.
# Below this, assume the page is an image.
MIN_CHARS_PER_PAGE = 120
# Fraction of pages that must look like image-only before we call the
# whole document scanned.
SCANNED_PAGE_RATIO = 0.60
# A line must appear on at least this fraction of pages to be treated as
# a running header/footer.
RUNNING_LINE_RATIO = 0.55


class PDFError(Exception):
    """Base class for anything that makes a PDF unusable."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(f"{path.name}: {message}")


class PDFOpenError(PDFError):
    """Corrupt, encrypted, or not a PDF at all."""


class ScannedPDFError(PDFError):
    """No usable text layer. Needs OCR before it can be ingested."""


class EmptyPDFError(PDFError):
    """Opened and has a text layer, but nothing survived cleaning."""


@dataclass
class Page:
    number: int  # 1-based
    text: str


@dataclass
class Document:
    path: Path
    pages: list[Page]
    pdf_title: str | None
    page_count: int

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def page_of_offset(self, offset: int) -> int:
        """Map a character offset in `self.text` back to a page number."""
        running = 0
        for p in self.pages:
            running += len(p.text) + 1
            if offset < running:
                return p.number
        return self.pages[-1].number if self.pages else 0


_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\u2018": "'", "\u2019": "'", "\u201c": '"',
    "\u201d": '"', "\u2013": "-", "\u2014": "—", "\u00a0": " ",
}


def _normalise(text: str) -> str:
    for bad, good in _LIGATURES.items():
        text = text.replace(bad, good)
    # Join words broken across a line break: "inven-\ntion" -> "invention".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Collapse runs of spaces but keep line structure — the sectioner
    # depends on line starts.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _mask_digits(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip())


def _find_running_lines(raw_pages: list[str]) -> set[str]:
    """Lines that repeat near the top or bottom of most pages."""
    if len(raw_pages) < 3:
        return set()
    counter: Counter[str] = Counter()
    for page in raw_pages:
        lines = [ln for ln in page.splitlines() if ln.strip()]
        candidates = lines[:2] + lines[-2:]
        for ln in set(_mask_digits(c) for c in candidates):
            if 2 < len(ln) < 120:
                counter[ln] += 1
    threshold = max(3, int(len(raw_pages) * RUNNING_LINE_RATIO))
    return {ln for ln, n in counter.items() if n >= threshold}


def _strip_running(page: str, running: set[str]) -> str:
    out = []
    for ln in page.splitlines():
        stripped = ln.strip()
        if not stripped:
            out.append("")
            continue
        if _mask_digits(stripped) in running:
            continue
        # Bare page numbers, and "Page 3 of 41".
        if re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", stripped):
            continue
        if re.fullmatch(r"(?i)page\s+\d+\s+of\s+\d+", stripped):
            continue
        out.append(ln.rstrip())
    return "\n".join(out)


def extract(path: Path | str) -> Document:
    """Extract normalised text, or raise a PDFError subclass.

    Raises:
        PDFOpenError: file is missing, encrypted, or unparseable.
        ScannedPDFError: no usable text layer (needs OCR).
        EmptyPDFError: text layer present but empty after cleaning.
    """
    path = Path(path)
    if not path.is_file():
        raise PDFOpenError(path, "file does not exist")

    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # pymupdf raises a variety of types
        raise PDFOpenError(path, f"could not open ({exc})") from exc

    try:
        if doc.needs_pass:
            raise PDFOpenError(path, "encrypted; supply a password before ingesting")
        if doc.page_count == 0:
            raise EmptyPDFError(path, "no pages")

        raw_pages: list[str] = []
        image_only = 0
        for page in doc:
            try:
                raw = page.get_text("text") or ""
            except Exception as exc:
                log.warning("%s p%d: text extraction failed (%s)", path.name, page.number + 1, exc)
                raw = ""
            if len(raw.strip()) < MIN_CHARS_PER_PAGE:
                image_only += 1
            raw_pages.append(raw)

        ratio = image_only / len(raw_pages)
        if ratio >= SCANNED_PAGE_RATIO:
            raise ScannedPDFError(
                path,
                f"{image_only}/{len(raw_pages)} pages have no usable text layer "
                f"({ratio:.0%}). Run OCR (ocrmypdf) and re-ingest.",
            )
        if image_only:
            log.warning(
                "%s: %d/%d pages look image-only; those pages will contribute nothing",
                path.name, image_only, len(raw_pages),
            )

        running = _find_running_lines(raw_pages)
        if running:
            log.info("%s: dropping %d running header/footer lines", path.name, len(running))

        pages = [
            Page(number=i + 1, text=_normalise(_strip_running(raw, running)))
            for i, raw in enumerate(raw_pages)
        ]
        title = (doc.metadata or {}).get("title") or None
        page_count = doc.page_count
    finally:
        doc.close()

    if not any(p.text.strip() for p in pages):
        raise EmptyPDFError(path, "no text survived cleaning")

    return Document(path=path, pages=pages, pdf_title=title, page_count=page_count)
