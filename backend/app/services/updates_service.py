from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.updates.orchestrator import publish as run_publish  # noqa: E402
from ai.updates.queue import ReviewQueue, ReviewQueueError  # noqa: E402
from ai.updates.scheduler import run_once  # noqa: E402

from ..config import settings  # noqa: E402


class UpdatesService:
    """Application-facing adapter around ai/updates — mirrors AIService's
    relationship to the ai/ RAG pipeline: this converts HTTP input into
    ai/updates calls and back, without owning any of that logic itself."""

    def __init__(self) -> None:
        self._queue: ReviewQueue | None = None

    @property
    def queue(self) -> ReviewQueue:
        if self._queue is None:
            self._queue = ReviewQueue(settings.updates_queue_db_path)
        return self._queue

    def check_now(self, *, auto_ingest: bool | None = None) -> dict[str, Any]:
        """Run one watch cycle synchronously and return what it found.
        `auto_ingest` overrides settings.updates_auto_ingest for this one
        call — useful for a demo/manual trigger without flipping the
        process-wide default."""
        results = run_once(
            sources_path=settings.updates_sources_path,
            watcher_db_path=settings.updates_watcher_db_path,
            queue_db_path=settings.updates_queue_db_path,
            stage_dir=settings.updates_stage_dir,
            manifest_path=settings.corpus_manifest_path,
            chroma_path=settings.chroma_path,
            chroma_collection=settings.chroma_collection,
            embedding_model=settings.embedding_model,
            embedding_device=settings.embedding_device,
            sqlite_registry_path=settings.sqlite_registry_path,
            auto_ingest=settings.updates_auto_ingest if auto_ingest is None else auto_ingest,
        )
        return {
            "checked": len(results),
            "entries": [{"id": eid, "tier": tier.value} for eid, tier in results],
        }

    def publish_entry(self, entry_id: str) -> dict[str, Any]:
        """Run the real ingestion pipeline for one queued_for_ingest or
        approved entry. Raises ReviewQueueError (-> 409) if the entry
        isn't in a publishable state, ValueError (-> 404-ish) if it does
        not exist."""
        from ai.embedder import get_embedder
        from ai.store import Registry, VectorStore

        embedder = get_embedder(settings.embedding_model, device=settings.embedding_device)
        registry = Registry(settings.sqlite_registry_path)
        try:
            vector_store = VectorStore(settings.chroma_path, collection=settings.chroma_collection)
            return run_publish(
                self.queue, entry_id,
                manifest_path=settings.corpus_manifest_path,
                embedder=embedder, registry=registry, vector_store=vector_store,
            )
        finally:
            registry.close()

    def approve(self, entry_id: str, *, decided_by: str, notes: str | None = None) -> None:
        self.queue.approve(entry_id, decided_by=decided_by, notes=notes)

    def reject(self, entry_id: str, *, decided_by: str, notes: str | None = None) -> None:
        self.queue.reject(entry_id, decided_by=decided_by, notes=notes)

    def clear_audit(self, entry_id: str, *, decided_by: str, notes: str | None = None) -> None:
        self.queue.clear_audit(entry_id, decided_by=decided_by, notes=notes)

    def pending(self) -> list[dict[str, Any]]:
        return self.queue.list_pending()

    def queued_for_ingest(self) -> list[dict[str, Any]]:
        return self.queue.list_queued_for_ingest()

    def needs_audit(self) -> list[dict[str, Any]]:
        return self.queue.list_needs_audit()

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.queue.list_history(limit=limit)


updates_service = UpdatesService()
