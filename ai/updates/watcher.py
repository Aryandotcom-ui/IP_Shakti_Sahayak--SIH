"""
ai/updates/watcher.py

Polls configured sources and reports which ones changed since the last
check. Follows the same SQLite-registry shape as `ai/store.py`: one table
holding the last-seen state, diffed against on every check.

Content identity, not text diffing
-----------------------------------
A source "changing" means its bytes hashed differently from last time.
That is deliberately crude — this module's job is to notice that
something moved and hand it to a human or the classifier, not to decide
whether the change is substantive. Real diffing (old section text vs new)
already exists in `ai/store.py`'s `content_hash` at the chunk level, once
a candidate is actually re-ingested through `ai/pipeline.py`.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .fetch import FetchError, Fetcher

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_state (
    url          TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    byte_size    INTEGER NOT NULL,
    first_seen   TEXT NOT NULL,
    last_checked TEXT NOT NULL,
    last_changed TEXT NOT NULL
);
"""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass
class SourceConfig:
    """One watched source, loaded from ai/updates/sources.yaml."""

    name: str
    url: str
    act_name: str
    jurisdiction: str
    # Reuses ai/corpus.yaml's acquisition-priority scale so the two lists
    # read the same way: critical/high/medium/low.
    priority: str = "medium"
    # "official" (a government/treaty portal) vs "unverified" (anything
    # else) — the classifier trusts a byte-diff on an official source far
    # more than the same diff on an unverified one.
    source_trust: str = "official"


def load_sources(path: Path | str) -> list[SourceConfig]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"sources manifest not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("sources", []) if isinstance(data, dict) else []
    return [
        SourceConfig(
            name=e["name"],
            url=e["url"],
            act_name=e["act_name"],
            jurisdiction=e.get("jurisdiction", "india"),
            priority=e.get("priority", "medium"),
            source_trust=e.get("source_trust", "official"),
        )
        for e in entries
    ]


@dataclass
class ChangeCandidate:
    """One source whose content hash differs from what was last seen (or
    is being seen for the first time)."""

    source: SourceConfig
    content: bytes
    content_hash: str
    previous_hash: str | None  # None means first-ever check for this URL
    previous_size: int | None
    checked_at: str

    @property
    def is_first_seen(self) -> bool:
        return self.previous_hash is None

    @property
    def byte_delta_ratio(self) -> float:
        """Fraction the byte size changed by, relative to the previous
        size. 1.0 (maximal) when there is no previous size to compare
        against, so a first-seen candidate never reads as a "small" change."""
        if not self.previous_size:
            return 1.0
        return abs(len(self.content) - self.previous_size) / self.previous_size


class SourceWatcher:
    """SQLite-backed last-seen-hash tracker for `check_all()`."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "SourceWatcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _last_state(self, url: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM source_state WHERE url = ?", (url,)
        ).fetchone()

    def _record_seen(self, url: str, content_hash: str, size: int, changed: bool) -> None:
        now = _now()
        existing = self._last_state(url)
        if existing is None:
            self.conn.execute(
                "INSERT INTO source_state "
                "(url, content_hash, byte_size, first_seen, last_checked, last_changed) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (url, content_hash, size, now, now, now),
            )
        else:
            self.conn.execute(
                "UPDATE source_state SET content_hash = ?, byte_size = ?, "
                "last_checked = ?, last_changed = ? WHERE url = ?",
                (content_hash, size, now, now if changed else existing["last_changed"], url),
            )
        self.conn.commit()

    def check_one(self, source: SourceConfig, fetcher: Fetcher) -> ChangeCandidate | None:
        """Fetch one source and return a ChangeCandidate if its content
        differs from what was last recorded (or nothing was recorded yet).
        Returns None on an unchanged source or a fetch failure — the
        latter is logged, not raised, so one dead link cannot sink a
        whole check cycle."""
        try:
            content = fetcher.fetch(source.url)
        except FetchError as exc:
            log.warning("source unreachable, skipping: %s", exc)
            return None

        new_hash = _hash(content)
        previous = self._last_state(source.url)
        previous_hash = previous["content_hash"] if previous else None
        previous_size = previous["byte_size"] if previous else None

        if previous_hash == new_hash:
            self._record_seen(source.url, new_hash, len(content), changed=False)
            return None

        candidate = ChangeCandidate(
            source=source,
            content=content,
            content_hash=new_hash,
            previous_hash=previous_hash,
            previous_size=previous_size,
            checked_at=_now(),
        )
        self._record_seen(source.url, new_hash, len(content), changed=True)
        return candidate

    def check_all(
        self, sources: list[SourceConfig], fetcher: Fetcher
    ) -> list[ChangeCandidate]:
        candidates = []
        for source in sources:
            candidate = self.check_one(source, fetcher)
            if candidate is not None:
                candidates.append(candidate)
        return candidates
