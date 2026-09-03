"""
ai/updates/orchestrator.py

Ties watcher -> classifier -> queue together, and separately, the one
step that actually touches the corpus: turning a staged file into
embedded chunks via the existing `ai.pipeline.ingest()`.

These are kept as two functions rather than one on purpose:

    run_check_cycle()   — detect + classify + stage + enqueue. No PDF
                           parsing, no embedding model, no Chroma. Safe
                           and fast to run on every scheduler tick, and
                           to unit test with nothing more than the
                           stdlib + PyYAML.

    publish()            — the heavy step: run a staged file through the
                           real ingestion pipeline. Called immediately
                           after enqueue for AUTO_PUBLISH and
                           PUBLISH_THEN_AUDIT tiers (when the caller
                           supplies the embedder/registry/vector store —
                           the scheduler does; a plain review-queue
                           listing does not need to), and called again,
                           later, for a MANDATORY_REVIEW item once a
                           human approves it.

A tier is a promise about *when* ingestion happens, not *whether* it is
the real pipeline: every tier that ends up published goes through the
same `ai.pipeline.ingest()` as a manually-run `python -m ai.cli`, with
the same validation and the same "one bad file never sinks the run"
error handling. AUTO_PUBLISH does not mean "trust blindly" — it means
"don't make a human wait for this one".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..embedder import Embedder
from ..metadata import load_manifest
from ..pipeline import ingest as run_ingest
from ..store import Registry, VectorStore
from .classify import Tier, classify
from .fetch import Fetcher
from .queue import ReviewQueue, ReviewQueueError
from .watcher import ChangeCandidate, SourceConfig, SourceWatcher

log = logging.getLogger(__name__)


def _stage(candidate: ChangeCandidate, stage_dir: Path) -> Path:
    """Write the fetched bytes to disk so ai.pipeline.ingest() — which
    operates on file paths, same as the manual CLI — can process it. The
    hash is in the filename so re-staging the same content is idempotent
    and two sources never collide."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(candidate.source.url).suffix or ".pdf"
    dest = stage_dir / f"{candidate.source.name}-{candidate.content_hash[:12]}{suffix}"
    dest.write_bytes(candidate.content)
    return dest


def run_check_cycle(
    sources: list[SourceConfig],
    *,
    watcher: SourceWatcher,
    fetcher: Fetcher,
    queue: ReviewQueue,
    stage_dir: Path | str,
) -> list[tuple[str, Tier]]:
    """One watch tick: check every source, classify what changed, stage
    the bytes, and enqueue. Returns (queue_entry_id, tier) pairs for
    everything found changed this cycle — the caller decides whether to
    immediately publish the auto-tier ones (see `publish()`)."""
    stage_dir = Path(stage_dir)
    results: list[tuple[str, Tier]] = []
    for candidate in watcher.check_all(sources, fetcher):
        result = classify(candidate)
        staged_path = _stage(candidate, stage_dir)
        entry_id = queue.enqueue(candidate, result, staged_path=str(staged_path))
        log.info(
            "%s: %s (%s)", candidate.source.name, result.tier.value, result.reason
        )
        results.append((entry_id, result.tier))
    return results


def publish(
    queue: ReviewQueue,
    entry_id: str,
    *,
    manifest_path: Path | str,
    embedder: Embedder,
    registry: Registry,
    vector_store: VectorStore,
) -> dict[str, Any]:
    """Run one queue entry's staged file through the real ingestion
    pipeline and record the outcome on the entry.

    Never raises for an ingestion failure — that is recorded via
    `mark_ingest_failed` and returned in the result, the same "one bad
    file must not sink anything" posture ai/pipeline.py itself takes for
    a single corrupt PDF. A completely unexpected error (a missing staged
    file, a broken manifest) is the one thing this does re-raise, since
    that points at the auto-update pipeline itself being broken rather
    than at the fetched document.
    """
    entry = queue.get(entry_id)
    if entry is None:
        raise ValueError(f"no review-queue entry {entry_id!r}")
    if entry["status"] not in ("queued_for_ingest", "approved"):
        raise ReviewQueueError(
            f"entry {entry_id!r} is {entry['status']!r}, not ready to publish "
            "(expected queued_for_ingest or approved)"
        )

    staged_path = entry.get("staged_path")
    if not staged_path:
        raise ValueError(f"entry {entry_id!r} has no staged file to ingest")

    manifest = load_manifest(manifest_path)
    chunks, report = run_ingest(
        [Path(staged_path)],
        manifest=manifest,
        embedder=embedder,
        registry=registry,
        vector_store=vector_store,
    )

    if report.failed:
        failure = report.failed[0]
        error = f"[{failure.error_type}] {failure.error}"
        queue.mark_ingest_failed(entry_id, error)
        return {"ok": False, "error": error}

    result = {"ok": True, "chunks": len(chunks), "embedder": report.embedder}
    queue.mark_published(entry_id, result)
    return result
