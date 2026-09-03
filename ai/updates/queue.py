"""
ai/updates/queue.py

The review gate's persistent state. Every ChangeCandidate the classifier
looks at gets one row here, whatever tier it lands in.

`status` tracks the ingestion lifecycle only:

    pending          -- MANDATORY_REVIEW tier, awaiting a human decision
    approved         -- a human said yes; not yet ingested
    rejected         -- a human said no; terminal
    queued_for_ingest -- AUTO_PUBLISH / PUBLISH_THEN_AUDIT tier, classifier
                        cleared it, not yet ingested (e.g. because
                        `updates_auto_ingest` is off — see backend config)
    published        -- ingested successfully, whichever path got it there
    ingest_failed    -- an ingest attempt ran and failed

`needs_audit` is a separate flag, not a status: PUBLISH_THEN_AUDIT items
are `published` (the corpus should not lag a real change) but also
`needs_audit = 1` until a human calls `clear_audit()`. Folding that into
`status` would force a choice between "this is published" and "this
needs review", when the whole point of that tier is that both are true
at once.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .classify import ClassificationResult, Tier
from .watcher import ChangeCandidate

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_queue (
    id             TEXT PRIMARY KEY,
    source_name    TEXT NOT NULL,
    url            TEXT NOT NULL,
    act_name       TEXT NOT NULL,
    jurisdiction   TEXT,
    tier           TEXT NOT NULL,
    reason         TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    previous_hash  TEXT,
    staged_path    TEXT,
    status         TEXT NOT NULL,   -- see module docstring
    needs_audit    INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    decided_at     TEXT,
    decided_by     TEXT,
    notes          TEXT,
    ingest_result  TEXT             -- JSON, set once an ingest attempt runs
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON review_queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_needs_audit ON review_queue(needs_audit);
"""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class ReviewQueueError(Exception):
    pass


class ReviewQueue:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ReviewQueue":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # enqueue
    # ------------------------------------------------------------------

    def enqueue(
        self,
        candidate: ChangeCandidate,
        result: ClassificationResult,
        *,
        staged_path: str | None = None,
    ) -> str:
        """Record one classified candidate. Returns its queue id.

        MANDATORY_REVIEW rows start `pending`; the other two tiers start
        `queued_for_ingest` — cleared to publish, but not yet ingested,
        since ingestion is the orchestrator's job (see `publish()` in
        orchestrator.py), not this class's.
        """
        entry_id = str(uuid.uuid4())
        status = "pending" if result.tier == Tier.MANDATORY_REVIEW else "queued_for_ingest"
        needs_audit = 1 if result.tier == Tier.PUBLISH_THEN_AUDIT else 0
        self.conn.execute(
            """
            INSERT INTO review_queue (
                id, source_name, url, act_name, jurisdiction, tier, reason,
                content_hash, previous_hash, staged_path, status,
                needs_audit, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id, candidate.source.name, candidate.source.url,
                candidate.source.act_name, candidate.source.jurisdiction,
                result.tier.value, result.reason, candidate.content_hash,
                candidate.previous_hash, staged_path, status, needs_audit, _now(),
            ),
        )
        self.conn.commit()
        return entry_id

    # ------------------------------------------------------------------
    # human decisions
    # ------------------------------------------------------------------

    def _require_status(self, entry_id: str, *expected: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM review_queue WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            raise ReviewQueueError(f"no review-queue entry {entry_id!r}")
        if row["status"] not in expected:
            raise ReviewQueueError(
                f"entry {entry_id!r} is {row['status']!r}, expected one of {expected}"
            )
        return row

    def approve(self, entry_id: str, *, decided_by: str, notes: str | None = None) -> None:
        """Mark a pending entry approved. Approval alone does not ingest
        anything — the caller is expected to attempt ingestion next via
        orchestrator.publish() and let mark_published()/mark_ingest_failed()
        record the outcome, so an approval that never got ingested is
        visibly distinct from one that did."""
        self._require_status(entry_id, "pending")
        self.conn.execute(
            "UPDATE review_queue SET status = 'approved', decided_at = ?, "
            "decided_by = ?, notes = ? WHERE id = ?",
            (_now(), decided_by, notes, entry_id),
        )
        self.conn.commit()

    def reject(self, entry_id: str, *, decided_by: str, notes: str | None = None) -> None:
        self._require_status(entry_id, "pending")
        self.conn.execute(
            "UPDATE review_queue SET status = 'rejected', decided_at = ?, "
            "decided_by = ?, notes = ? WHERE id = ?",
            (_now(), decided_by, notes, entry_id),
        )
        self.conn.commit()

    def mark_published(self, entry_id: str, ingest_result: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "UPDATE review_queue SET status = 'published', ingest_result = ? WHERE id = ?",
            (json.dumps(ingest_result) if ingest_result is not None else None, entry_id),
        )
        self.conn.commit()

    def mark_ingest_failed(self, entry_id: str, error: str) -> None:
        """An approved (or auto-tier) item whose ingest attempt failed.
        Falls back to `ingest_failed` rather than silently staying
        `approved`/`queued_for_ingest` — a failed publish must be as
        visible as a pending one, not disappear into a status that reads
        as done."""
        self.conn.execute(
            "UPDATE review_queue SET status = 'ingest_failed', ingest_result = ? WHERE id = ?",
            (json.dumps({"error": error}), entry_id),
        )
        self.conn.commit()

    def clear_audit(self, entry_id: str, *, decided_by: str, notes: str | None = None) -> None:
        """A human has reviewed a PUBLISH_THEN_AUDIT item that was already
        ingested and signs off on it (or would follow this with a manual
        retraction if they didn't — retraction itself is a corpus-registry
        operation, out of scope for this queue). Does not touch `status`:
        the item was, and remains, published."""
        row = self.conn.execute(
            "SELECT * FROM review_queue WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            raise ReviewQueueError(f"no review-queue entry {entry_id!r}")
        if not row["needs_audit"]:
            raise ReviewQueueError(f"entry {entry_id!r} does not need audit")
        self.conn.execute(
            "UPDATE review_queue SET needs_audit = 0, decided_at = ?, "
            "decided_by = ?, notes = ? WHERE id = ?",
            (_now(), decided_by, notes, entry_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def get(self, entry_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM review_queue WHERE id = ?", (entry_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_pending(self) -> list[dict[str, Any]]:
        """MANDATORY_REVIEW items awaiting a pre-publish decision."""
        rows = self.conn.execute(
            "SELECT * FROM review_queue WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_queued_for_ingest(self) -> list[dict[str, Any]]:
        """AUTO_PUBLISH / PUBLISH_THEN_AUDIT items cleared but not yet
        ingested — the backlog `updates_auto_ingest=False` leaves behind
        for an operator to publish explicitly."""
        rows = self.conn.execute(
            "SELECT * FROM review_queue WHERE status = 'queued_for_ingest' "
            "ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_needs_audit(self) -> list[dict[str, Any]]:
        """Already-published PUBLISH_THEN_AUDIT items awaiting the
        after-the-fact human sign-off that tier promises."""
        rows = self.conn.execute(
            "SELECT * FROM review_queue WHERE needs_audit = 1 AND status = 'published' "
            "ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM review_queue WHERE status NOT IN ('pending', 'queued_for_ingest') "
            "ORDER BY COALESCE(decided_at, created_at) DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
