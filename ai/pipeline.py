"""End-to-end ingestion.

    PDFs -> extract -> section -> chunk -> metadata -> validate
         -> SQLite (version tracking) -> embed only what changed -> Chroma

Embedding runs *after* the registry diff, so a re-ingest of an unchanged
corpus costs nothing. On a 600-chunk corpus that is the difference
between a two-minute run and a two-second one, which is what makes it
realistic to re-ingest on every merge.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .embedder import Embedder
from .extract import Document, PDFError, extract
from .metadata import DocMeta, resolve
from .schema import Chunk, SchemaError, slugify, validate_all
from .sectioner import chunk_sections, find_sections
from .store import Registry, VectorStore, WriteStats

log = logging.getLogger(__name__)


@dataclass
class FileReport:
    path: Path
    ok: bool
    chunks: int = 0
    error: str | None = None
    error_type: str | None = None


@dataclass
class IngestReport:
    files: list[FileReport] = field(default_factory=list)
    stats: WriteStats = field(default_factory=WriteStats)
    orphans: list[str] = field(default_factory=list)
    embedder: str = ""

    @property
    def ok(self) -> list[FileReport]:
        return [f for f in self.files if f.ok]

    @property
    def failed(self) -> list[FileReport]:
        return [f for f in self.files if not f.ok]

    @property
    def total_chunks(self) -> int:
        return sum(f.chunks for f in self.ok)

    def summary(self) -> str:
        lines = [
            "",
            "  ingest summary",
            "  " + "-" * 58,
            f"  files processed   {len(self.ok)} ok, {len(self.failed)} failed",
            f"  chunks produced   {self.total_chunks}",
            f"  registry          {self.stats.new} new, {self.stats.changed} changed, "
            f"{self.stats.unchanged} unchanged",
            f"  embedded          {self.stats.written} (skipped {self.stats.unchanged})",
            f"  embedder          {self.embedder}",
        ]
        if self.orphans:
            lines.append(f"  orphaned          {len(self.orphans)} chunk ids no longer produced")
            for cid in self.orphans[:5]:
                lines.append(f"                    {cid}")
            if len(self.orphans) > 5:
                lines.append(f"                    ... and {len(self.orphans) - 5} more")
        if self.failed:
            lines.append("  " + "-" * 58)
            for f in self.failed:
                lines.append(f"  FAILED {f.path.name}: [{f.error_type}] {f.error}")
        lines.append("")
        return "\n".join(lines)


def build_chunks(doc: Document, meta: DocMeta) -> list[Chunk]:
    """Section a document and attach metadata to each chunk."""
    sections = find_sections(doc.text)
    if not sections:
        log.warning("%s: no sections detected", doc.path.name)
        return []

    act_slug = slugify(meta.act_name, max_len=40)
    chunks: list[Chunk] = []

    for section, part_suffix, text in chunk_sections(sections):
        label = section.label
        section_slug = slugify(label.replace("Section ", "s").replace("Article ", "art")
                               .replace("Rule ", "r"), max_len=24)
        chunk_id = f"{act_slug}--{section_slug}"
        if part_suffix:
            chunk_id = f"{chunk_id}--{part_suffix}"

        effective_date, date_source = meta.effective_date_for(label, section.number)

        # Prepend the citation so the chunk is self-describing: the
        # embedding then carries the locator, and a retrieved chunk read
        # in isolation still says what it is.
        header = f"{meta.act_name} — {label}"
        if section.heading:
            header += f": {section.heading}"
        body = text if text.startswith(header) else f"{header}\n\n{text}"

        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                text=body,
                jurisdiction=meta.jurisdiction,
                instrument_type=meta.instrument_type,
                act_name=meta.act_name,
                section=label,
                effective_date=effective_date,
                source_url=meta.source_url,
                provenance={
                    "source_file": doc.path.name,
                    "page": doc.page_of_offset(section.start_offset),
                    "chapter": section.chapter,
                    "heading": section.heading,
                    "part": part_suffix or None,
                    "char_len": len(body),
                    "metadata_sources": dict(meta.sources, effective_date=date_source),
                    "extracted_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                },
            )
        )

    # Disambiguate any id collision (two documents legitimately sharing a
    # section label, or a renumbered schedule) rather than dropping one.
    seen: dict[str, int] = {}
    for c in chunks:
        if c.chunk_id in seen:
            seen[c.chunk_id] += 1
            c.chunk_id = f"{c.chunk_id}--{seen[c.chunk_id]}"
            log.debug("disambiguated duplicate chunk_id -> %s", c.chunk_id)
        else:
            seen[c.chunk_id] = 0

    return chunks


def process_file(
    path: Path,
    manifest: dict[str, dict[str, Any]],
    *,
    interactive: bool = False,
    strict: bool = False,
) -> tuple[list[Chunk], FileReport]:
    """Extract and chunk one PDF. Never raises for a bad PDF — the error
    goes into the report so a 40-file run is not sunk by one scan."""
    try:
        doc = extract(path)
        meta = resolve(doc, manifest, interactive=interactive, strict=strict)
        chunks = build_chunks(doc, meta)
        validate_all(chunks)
        if not chunks:
            return [], FileReport(path, False, 0, "no sections detected", "EmptySection")
        log.info("%s: %d chunks (%s, %s)", path.name, len(chunks),
                 meta.jurisdiction, meta.instrument_type)
        return chunks, FileReport(path, True, len(chunks))
    except PDFError as exc:
        log.error("%s", exc)
        return [], FileReport(path, False, 0, str(exc), type(exc).__name__)
    except SchemaError as exc:
        log.error("%s: schema violation: %s", path.name, exc)
        return [], FileReport(path, False, 0, str(exc), "SchemaError")
    except Exception as exc:  # noqa: BLE001 — one bad file must not sink the run
        log.exception("%s: unexpected failure", path.name)
        return [], FileReport(path, False, 0, str(exc), type(exc).__name__)


def ingest(
    pdf_paths: list[Path],
    *,
    manifest: dict[str, dict[str, Any]],
    embedder: Embedder,
    registry: Registry,
    vector_store: VectorStore | None,
    interactive: bool = False,
    strict: bool = False,
    dry_run: bool = False,
) -> tuple[list[Chunk], IngestReport]:
    report = IngestReport(embedder=getattr(embedder, "name", "unknown"))
    all_chunks: list[Chunk] = []

    for path in pdf_paths:
        chunks, file_report = process_file(
            path, manifest, interactive=interactive, strict=strict
        )
        report.files.append(file_report)
        all_chunks.extend(chunks)

    if dry_run:
        log.info("dry run: %d chunks produced, nothing written", len(all_chunks))
        return all_chunks, report

    run_id = registry.start_run(report.embedder, notes=f"{len(pdf_paths)} files")
    stats, dirty = registry.upsert(all_chunks)
    report.stats = stats

    # A TF-IDF-style embedder learns its vector space from the corpus, so
    # it has to see the text before it can encode any of it. Fit on every
    # chunk rather than only the dirty ones: the vocabulary should describe
    # the whole corpus, or a re-ingest of two changed files would silently
    # rebuild the space around those two files.
    if dirty and vector_store is not None and hasattr(embedder, "fit"):
        if not getattr(embedder, "fitted", True):
            embedder.fit([c.text for c in all_chunks])

    if dirty and vector_store is not None:
        log.info("embedding %d new/changed chunks", len(dirty))
        # Batch so a large corpus does not build one enormous list.
        batch = 64
        for i in range(0, len(dirty), batch):
            window = dirty[i : i + batch]
            vector_store.upsert(window, embedder.encode([c.text for c in window]))
        log.info("vector store now holds %d chunks", vector_store.count())

    report.orphans = registry.orphans(c.chunk_id for c in all_chunks)
    registry.finish_run(run_id, stats, len(report.ok), len(report.failed))
    return all_chunks, report
