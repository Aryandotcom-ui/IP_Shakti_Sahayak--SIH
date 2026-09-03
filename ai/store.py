"""Persistence: ChromaDB for vectors, SQLite for version tracking.

The SQLite side is the source of truth about *what we have ingested and
when*. Chroma is a derived index — if it is ever lost, it can be rebuilt
from the PDFs plus this registry.

`chunks` holds exactly the four columns the team agreed on. `chunk_versions`
sits alongside it and keeps the history, which is what makes the corpus
"version-tracked" rather than merely "timestamped": when a provision's
text changes, the old hash is closed out with a `superseded_at` and the
new one opened. That history is what lets you answer "what did this say
in 2022?" and audit when a chunk silently changed under you.
"""

from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .schema import Chunk

log = logging.getLogger(__name__)

COLLECTION = "ip_sakti_corpus"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,
    source_url   TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    ingested_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id      TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    source_file   TEXT,
    act_name      TEXT,
    section       TEXT,
    effective_date TEXT,
    first_seen    TEXT NOT NULL,
    superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_versions_chunk ON chunk_versions(chunk_id);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    files_ok    INTEGER DEFAULT 0,
    files_failed INTEGER DEFAULT 0,
    chunks_new  INTEGER DEFAULT 0,
    chunks_changed INTEGER DEFAULT 0,
    chunks_unchanged INTEGER DEFAULT 0,
    embedder    TEXT,
    notes       TEXT
);
"""


@dataclass
class WriteStats:
    new: int = 0
    changed: int = 0
    unchanged: int = 0

    @property
    def written(self) -> int:
        return self.new + self.changed


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class Registry:
    """SQLite version tracking."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Registry":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def known_hashes(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT chunk_id, content_hash FROM chunks").fetchall()
        return {r["chunk_id"]: r["content_hash"] for r in rows}

    def start_run(self, embedder: str, notes: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO ingest_runs (started_at, embedder, notes) VALUES (?,?,?)",
            (_now(), embedder, notes),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, stats: WriteStats, ok: int, failed: int) -> None:
        self.conn.execute(
            "UPDATE ingest_runs SET finished_at=?, files_ok=?, files_failed=?, "
            "chunks_new=?, chunks_changed=?, chunks_unchanged=? WHERE id=?",
            (_now(), ok, failed, stats.new, stats.changed, stats.unchanged, run_id),
        )
        self.conn.commit()

    def upsert(self, chunks: Sequence[Chunk]) -> tuple[WriteStats, list[Chunk]]:
        """Record chunks and return (stats, chunks that need re-embedding)."""
        known = self.known_hashes()
        stats = WriteStats()
        dirty: list[Chunk] = []
        now = _now()

        for c in chunks:
            h = c.content_hash
            prior = known.get(c.chunk_id)
            if prior == h:
                stats.unchanged += 1
                continue

            if prior is None:
                stats.new += 1
            else:
                stats.changed += 1
                self.conn.execute(
                    "UPDATE chunk_versions SET superseded_at=? "
                    "WHERE chunk_id=? AND superseded_at IS NULL",
                    (now, c.chunk_id),
                )
                log.info("chunk %s changed (%s -> %s)", c.chunk_id, prior[:8], h[:8])

            self.conn.execute(
                "INSERT INTO chunks (chunk_id, source_url, content_hash, ingested_at) "
                "VALUES (?,?,?,?) ON CONFLICT(chunk_id) DO UPDATE SET "
                "source_url=excluded.source_url, content_hash=excluded.content_hash, "
                "ingested_at=excluded.ingested_at",
                (c.chunk_id, c.source_url, h, now),
            )
            self.conn.execute(
                "INSERT INTO chunk_versions (chunk_id, content_hash, source_file, act_name, "
                "section, effective_date, first_seen) VALUES (?,?,?,?,?,?,?)",
                (c.chunk_id, h, str(c.provenance.get("source_file", "")), c.act_name,
                 c.section, c.effective_date, now),
            )
            dirty.append(c)

        self.conn.commit()
        return stats, dirty

    def orphans(self, current_ids: Iterable[str]) -> list[str]:
        """Chunk ids in the registry that this run did not produce.

        Usually means a section was renumbered or a source withdrawn.
        Reported, never auto-deleted — deleting corpus without a human
        looking at it is how a citation quietly disappears.
        """
        current = set(current_ids)
        return [cid for cid in self.known_hashes() if cid not in current]


class VectorStore:
    """ChromaDB persistent collection."""

    def __init__(self, path: Path | str, collection: str = COLLECTION) -> None:
        import chromadb

        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.path))

        self.collection = self.client.get_or_create_collection(
            name=collection,
            metadata={"hnsw:space": "cosine"}
        )

    def upsert(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]]
    ) -> None:
        if not chunks:
            return

        if len(chunks) != len(embeddings):
            raise ValueError("chunk/embedding count mismatch")

        self.collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=[list(e) for e in embeddings],
            metadatas=[
                {
                    "jurisdiction": c.jurisdiction,
                    "instrument_type": c.instrument_type,
                    "act_name": c.act_name,
                    "section": c.section,
                    "effective_date": c.effective_date,
                    "source_url": c.source_url,
                    "content_hash": c.content_hash,
                }
                for c in chunks
            ],
        )

    def count(self) -> int:
        return int(self.collection.count())

    def query(
        self,
        query: str,
        embedder,
        jurisdiction: str | None = None,
        formulation_type: str | None = None,
        top_k: int = 5,
    ) -> dict:
        """Query ChromaDB and return retrieval results."""

        query_embedding = embedder.encode_query([query])[0]

        conditions = []

        if jurisdiction:
            conditions.append({
                "jurisdiction": jurisdiction
            })

        if formulation_type:
            conditions.append({
                "instrument_type": formulation_type
            })

        where = None

        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        result = self.collection.query(
            query_embeddings=[list(query_embedding)],
            n_results=top_k,
            where=where,
            include=[
                "documents",
                "metadatas",
                "distances"
            ],
        )

        matches = []

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        for i, chunk_id in enumerate(ids):
            metadata = metadatas[i] or {}

            distance = distances[i] if i < len(distances) else 1.0

            similarity = max(
                0.0,
                min(1.0, 1.0 - float(distance))
            )

            matches.append({
                "chunk_id": chunk_id,
                "text": documents[i] if i < len(documents) else "",
                "act_name": metadata.get("act_name"),
                "section": metadata.get("section"),
                "jurisdiction": metadata.get("jurisdiction"),
                "similarity_score": similarity,
                "source_url": metadata.get("source_url"),
            })

        return {
            "matches": matches
        }