"""
ai/updates/scheduler.py

Thin APScheduler wrapper around one job: run a check cycle, and for
anything the classifier cleared for immediate ingestion, publish it.

Import-guarded: `apscheduler` is an optional dependency of the backend
(see backend/requirements.txt). A deployment that has not installed it
still boots — `start_scheduler()` logs a warning and returns None rather
than raising, the same degrade-don't-crash posture
`ai/person_b_retrieval/embeddings.py` takes on a missing model and
`ai/compliance/tkdl.py`'s `NullProbe` takes on an unavailable prior-art
source.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..embedder import Embedder, get_embedder
from ..store import Registry, VectorStore
from .classify import Tier
from .fetch import Fetcher, HttpFetcher
from .orchestrator import publish, run_check_cycle
from .queue import ReviewQueue
from .watcher import SourceWatcher, load_sources

log = logging.getLogger(__name__)

_AUTO_INGEST_TIERS = {Tier.AUTO_PUBLISH, Tier.PUBLISH_THEN_AUDIT}


def run_once(
    *,
    sources_path: Path | str,
    watcher_db_path: Path | str,
    queue_db_path: Path | str,
    stage_dir: Path | str,
    manifest_path: Path | str,
    chroma_path: Path | str,
    chroma_collection: str,
    embedding_model: str,
    embedding_device: str | None,
    sqlite_registry_path: Path | str,
    fetcher: Fetcher | None = None,
    auto_ingest: bool = True,
) -> list[tuple[str, Tier]]:
    """One full tick: check every configured source, classify, stage,
    enqueue, and — for AUTO_PUBLISH / PUBLISH_THEN_AUDIT tiers, when
    `auto_ingest` is true — ingest immediately. Safe to call directly
    (e.g. from a "check now" API endpoint) without a scheduler running."""
    sources = load_sources(sources_path)
    fetcher = fetcher or HttpFetcher()

    with SourceWatcher(watcher_db_path) as watcher, ReviewQueue(queue_db_path) as queue:
        results = run_check_cycle(
            sources, watcher=watcher, fetcher=fetcher, queue=queue, stage_dir=stage_dir
        )

        if auto_ingest:
            to_publish = [eid for eid, tier in results if tier in _AUTO_INGEST_TIERS]
            if to_publish:
                embedder = get_embedder(embedding_model, device=embedding_device)
                registry = Registry(sqlite_registry_path)
                vector_store = VectorStore(chroma_path, collection=chroma_collection)
                try:
                    for entry_id in to_publish:
                        try:
                            publish(
                                queue, entry_id,
                                manifest_path=manifest_path, embedder=embedder,
                                registry=registry, vector_store=vector_store,
                            )
                        except Exception:
                            # One entry's staged file being unreadable, or the
                            # manifest being briefly unavailable, must not
                            # stop the rest of the batch from publishing —
                            # same "one bad file never sinks the run"
                            # posture as ai/pipeline.py.
                            log.exception("publish failed for queue entry %s", entry_id)
                finally:
                    registry.close()

    return results


def start_scheduler(
    *,
    interval_minutes: int,
    sources_path: Path | str,
    watcher_db_path: Path | str,
    queue_db_path: Path | str,
    stage_dir: Path | str,
    manifest_path: Path | str,
    chroma_path: Path | str,
    chroma_collection: str,
    embedding_model: str,
    embedding_device: str | None,
    sqlite_registry_path: Path | str,
    auto_ingest: bool = True,
):
    """Start a background job that calls `run_once()` on a fixed
    interval. Returns the scheduler (call `.shutdown()` on it at process
    exit) or None if APScheduler is not installed."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        log.warning(
            "apscheduler not installed — the auto-update source watcher will "
            "not run on a schedule. Install it (see backend/requirements.txt) "
            "or trigger ai.updates.scheduler.run_once() manually / via the "
            "\"check now\" API endpoint."
        )
        return None

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_once,
        trigger="interval",
        minutes=interval_minutes,
        kwargs=dict(
            sources_path=sources_path,
            watcher_db_path=watcher_db_path,
            queue_db_path=queue_db_path,
            stage_dir=stage_dir,
            manifest_path=manifest_path,
            chroma_path=chroma_path,
            chroma_collection=chroma_collection,
            embedding_model=embedding_model,
            embedding_device=embedding_device,
            sqlite_registry_path=sqlite_registry_path,
            auto_ingest=auto_ingest,
        ),
        id="source-watch-cycle",
        replace_existing=True,
        # A tick that is still running when the next one is due is a sign
        # something (network, embedding) is slow, not a reason to pile up
        # concurrent ingests against the same SQLite registry.
        max_instances=1,
    )
    scheduler.start()
    log.info("auto-update scheduler started: every %d minute(s)", interval_minutes)
    return scheduler
