#!/usr/bin/env python3
"""Dump 5 sample chunks to sample_output.json for integration testing.

Deliberately picks a *spread* rather than the first five: both
jurisdictions, several instrument types, and one multi-part chunk if the
corpus has one. Whoever is building retrieval needs to see a treaty
article and a split section, not five consecutive sections of the same
Act — the edge cases are where their filters will break.

    python scripts/dump_samples.py data/pdfs --manifest manifests/corpus.yaml
    python scripts/dump_samples.py --from-json build/chunks.json -n 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.embedder import HashingEmbedder  # noqa: E402
from ingest.metadata import load_manifest  # noqa: E402
from ingest.pipeline import process_file  # noqa: E402
from ingest.schema import SCHEMA_KEYS, Chunk  # noqa: E402


def pick_spread(chunks: list[Chunk], n: int) -> list[Chunk]:
    """Greedily choose chunks that differ from what is already picked."""
    if len(chunks) <= n:
        return chunks

    picked: list[Chunk] = []
    seen_keys: set[tuple[str, str]] = set()

    # Preambles are the least useful thing to hand a teammate — every
    # document has one and none of them exercise the section logic.
    # Order them last, but keep them available if the corpus is thin.
    ordered = sorted(chunks, key=lambda c: c.section.lower().startswith("preamble"))

    # Pass 1: one per (jurisdiction, instrument_type) combination.
    for c in ordered:
        key = (c.jurisdiction, c.instrument_type)
        if key not in seen_keys:
            seen_keys.add(key)
            picked.append(c)
        if len(picked) == n:
            return picked

    # Pass 2: a multi-part chunk, which is the case integration usually breaks on.
    multipart = [c for c in chunks if c.provenance.get("part") and c not in picked]
    if multipart and len(picked) < n:
        picked.append(multipart[0])

    # Pass 3: spread across the remainder by position.
    remaining = [c for c in ordered if c not in picked]
    if remaining and len(picked) < n:
        need = n - len(picked)
        step = max(1, len(remaining) // need)
        picked.extend(remaining[::step][:need])

    return picked[:n]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="*", help="PDF files or directories")
    ap.add_argument("--from-json", default=None,
                    help="read chunks from a previous --json-out instead of re-ingesting")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("-o", "--out", default="sample_output.json")
    ap.add_argument("--with-embedding-preview", action="store_true",
                    help="append the first 8 dims of a placeholder vector (debug only)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s",
                        stream=sys.stderr)

    chunks: list[Chunk] = []
    if args.from_json:
        raw = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        chunks = [Chunk(**{k: r[k] for k in SCHEMA_KEYS}) for r in raw]
    else:
        if not args.inputs:
            ap.error("give PDF paths or --from-json")
        manifest = load_manifest(args.manifest)
        paths: list[Path] = []
        for item in args.inputs:
            p = Path(item)
            paths.extend(sorted(p.rglob("*.pdf")) if p.is_dir() else [p])
        for p in paths:
            got, report = process_file(p, manifest)
            if not report.ok:
                logging.warning("skipped %s: %s", p.name, report.error)
            chunks.extend(got)

    if not chunks:
        logging.error("no chunks produced — nothing to sample")
        return 1

    samples = pick_spread(chunks, args.n)
    payload = [c.to_dict() for c in samples]

    if args.with_embedding_preview:
        vectors = HashingEmbedder().encode([c.text for c in samples])
        for row, vec in zip(payload, vectors):
            row["_embedding_preview"] = [round(v, 6) for v in vec[:8]]

    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"wrote {len(payload)} of {len(chunks)} chunks to {out}", file=sys.stderr)
    for c in samples:
        print(f"  {c.chunk_id:<50} {c.jurisdiction:<14} {c.instrument_type:<9} "
              f"{c.section} ({len(c.text)} chars)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
