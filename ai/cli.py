"""Command line entrypoint.

    python -m ai.cli data/pdfs --manifest ai/corpus.yaml
    python -m ai.cli data/pdfs --dry-run --json-out build/chunks.json
    python -m ai.cli data/pdfs/new.pdf --interactive
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .embedder import DEFAULT_MODEL, get_embedder
from .metadata import MetadataError, load_manifest
from .pipeline import ingest
from .store import Registry, VectorStore


def _collect_pdfs(inputs: list[str]) -> list[Path]:
    out: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            out.extend(sorted(p.rglob("*.pdf")))
        elif p.is_file():
            out.append(p)
        else:
            logging.warning("skipping %s: not a file or directory", p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ingest",
        description="Ingest legal PDFs into the IP-SAKTI corpus.",
    )
    ap.add_argument("inputs", nargs="+", help="PDF files or directories")
    ap.add_argument("--manifest", default=None, help="YAML/JSON metadata manifest")
    ap.add_argument("--chroma-path", default="data/chroma")
    ap.add_argument("--sqlite-path", default="data/registry.sqlite3")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default=None, help="cpu | cuda | mps")
    ap.add_argument("--allow-fallback-embeddings", action="store_true",
                    help="run with placeholder vectors if the model is unavailable")
    ap.add_argument("--interactive", action="store_true",
                    help="prompt for metadata fields missing from the manifest")
    ap.add_argument("--strict", action="store_true",
                    help="fail rather than infer any metadata field")
    ap.add_argument("--dry-run", action="store_true",
                    help="chunk and validate only; write nothing")
    ap.add_argument("--json-out", default=None, help="write all chunks as JSON")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    pdfs = _collect_pdfs(args.inputs)
    if not pdfs:
        logging.error("no PDFs found in %s", args.inputs)
        return 2
    logging.info("found %d PDF(s)", len(pdfs))

    try:
        manifest = load_manifest(args.manifest)
    except MetadataError as exc:
        logging.error("%s", exc)
        return 2
    if args.manifest:
        missing = [p.name for p in pdfs if p.name not in manifest]
        if missing:
            logging.warning("not in manifest (metadata will be inferred): %s",
                            ", ".join(missing[:8]) + ("..." if len(missing) > 8 else ""))

    embedder = None
    if not args.dry_run:
        try:
            embedder = get_embedder(
                args.model,
                allow_fallback=args.allow_fallback_embeddings,
                device=args.device,
            )
        except RuntimeError as exc:
            logging.error("%s", exc)
            return 3
    else:
        from .embedder import HashingEmbedder
        embedder = HashingEmbedder()

    registry = Registry(args.sqlite_path)
    store = None if args.dry_run else VectorStore(args.chroma_path)
    try:
        chunks, report = ingest(
            pdfs,
            manifest=manifest,
            embedder=embedder,
            registry=registry,
            vector_store=store,
            interactive=args.interactive,
            strict=args.strict,
            dry_run=args.dry_run,
        )
    finally:
        registry.close()

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps([c.to_dict() for c in chunks], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logging.info("wrote %d chunks to %s", len(chunks), out)

    print(report.summary(), file=sys.stderr)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
