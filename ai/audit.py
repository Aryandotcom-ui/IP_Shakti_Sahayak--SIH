"""
ai/audit.py

DPDP-aligned audit trail for the query endpoint.

Why this exists
----------------
The Digital Personal Data Protection Act, 2023 asks two things of a system
that processes a person's query and returns a decision-relevant answer:
someone must be able to reconstruct what was processed and when (an audit
trail), and processing that depends on the requester's agreement needs that
agreement captured before it happens, not asserted after the fact. Neither
existed here — a query touched no persistent record once the HTTP response
left the process.

This module logs every query that goes through `AIService.answer()`: the
query text, the retrieval that ran, the confidence and citations returned,
and whether any of those citations required consent that was or was not
given. It follows the same SQLite-registry pattern as `ai/store.py`: one
file, one schema, one class.

Consent for licensed sources
-----------------------------
A `corpus.yaml` document can be marked `access: licensed` (see its header
comment). A query whose retrieval matches a licensed act, submitted
without consent for that specific act, has that citation withheld from
the response — the question still gets answered from whatever public
sources matched, but never from a licensed one the requester has not
agreed to use. This is a withhold, not a downgrade to "abstain":
abstention means the corpus lacks an answer, which is a different claim
from "an answer exists but the requester has not consented to it."

Consent is requested per act_name, not as one blanket flag, because DPDP
consent has to be for a specified purpose — "yes to everything the corpus
might ever charge for" is not that.

What is deliberately NOT here
-------------------------------
No PII scrubbing of the query text. The audit trail's purpose is to let
the query be reconstructed, which the audit-trail duty requires; logging a
redacted query cannot serve that duty. What DPDP's storage-limitation
principle does ask for is a retention bound, which is `purge_older_than()`
— call it from a scheduled job (see the gap-5 auto-update pipeline) rather
than never at all.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id                     TEXT PRIMARY KEY,
    ts                     TEXT NOT NULL,
    query_text             TEXT NOT NULL,
    jurisdiction           TEXT,
    formulation_type       TEXT,
    top_k                  INTEGER,
    matched_chunk_ids      TEXT NOT NULL,   -- JSON list[str]
    confidence             REAL,
    should_abstain         INTEGER NOT NULL,
    citations              TEXT NOT NULL,   -- JSON list[{act_name, section}], post-gate
    licensed_acts_matched  TEXT NOT NULL,   -- JSON list[str]
    licensed_acts_withheld TEXT NOT NULL,   -- JSON list[str] -- subset lacking consent
    consent_given          INTEGER,         -- NULL: nothing licensed matched, gate not applicable
    disclaimer_shown       INTEGER NOT NULL,
    llm_model              TEXT,
    error                  TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS consent_log (
    id         TEXT PRIMARY KEY,
    ts         TEXT NOT NULL,
    query_id   TEXT NOT NULL,
    act_name   TEXT NOT NULL,
    granted    INTEGER NOT NULL,
    FOREIGN KEY (query_id) REFERENCES audit_log(id)
);
CREATE INDEX IF NOT EXISTS idx_consent_query ON consent_log(query_id);
"""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class CitationGate:
    """Result of checking a set of matched act_names against consent."""

    licensed_matched: list[str] = field(default_factory=list)
    licensed_withheld: list[str] = field(default_factory=list)
    # None means nothing licensed matched, so consent was not applicable —
    # distinct from False, which means it was asked for and refused/absent.
    consent_given: bool | None = None


def load_access_map(corpus_path: Path | str) -> dict[str, str]:
    """act_name -> "public" | "licensed", read straight from corpus.yaml.

    Not cached at module level: the manifest is small and each AIService
    process holds one AuditLog instance that reads it once at construction,
    which is enough. A hot-reload story is out of scope here.
    """
    path = Path(corpus_path)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    documents = data.get("documents", []) if isinstance(data, dict) else []
    out: dict[str, str] = {}
    for entry in documents:
        act_name = entry.get("act_name")
        if act_name:
            out[act_name] = entry.get("access", "public")
    return out


class AuditLog:
    """SQLite-backed query audit trail with licensed-source consent gating."""

    def __init__(self, path: Path | str, corpus_path: Path | str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        self._access_map = load_access_map(corpus_path) if corpus_path else {}

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # consent gating
    # ------------------------------------------------------------------

    def gate_citations(
        self,
        act_names: Iterable[str],
        *,
        consented_acts: set[str] | None = None,
    ) -> CitationGate:
        """Split matched act_names into what's licensed and, of those,
        what lacks consent. `consented_acts` is the set of act_names the
        request explicitly consented to; omitted or empty means consent
        was given for nothing."""
        consented_acts = consented_acts or set()
        licensed_matched = sorted({
            a for a in act_names if self._access_map.get(a) == "licensed"
        })
        if not licensed_matched:
            return CitationGate()
        withheld = sorted(a for a in licensed_matched if a not in consented_acts)
        return CitationGate(
            licensed_matched=licensed_matched,
            licensed_withheld=withheld,
            consent_given=(len(withheld) == 0),
        )

    # ------------------------------------------------------------------
    # logging
    # ------------------------------------------------------------------

    def log_query(
        self,
        *,
        query_text: str,
        jurisdiction: str | None,
        formulation_type: str | None,
        top_k: int,
        matched_chunk_ids: list[str],
        confidence: float | None,
        should_abstain: bool,
        citations: list[dict[str, Any]],
        gate: CitationGate | None = None,
        disclaimer_shown: bool = True,
        llm_model: str | None = None,
        error: str | None = None,
    ) -> str:
        """Write one row. Returns the audit entry id."""
        gate = gate or CitationGate()
        query_id = str(uuid.uuid4())
        ts = _now()
        self.conn.execute(
            """
            INSERT INTO audit_log (
                id, ts, query_text, jurisdiction, formulation_type, top_k,
                matched_chunk_ids, confidence, should_abstain, citations,
                licensed_acts_matched, licensed_acts_withheld, consent_given,
                disclaimer_shown, llm_model, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query_id, ts, query_text, jurisdiction, formulation_type, top_k,
                json.dumps(matched_chunk_ids), confidence, int(should_abstain),
                json.dumps(citations), json.dumps(gate.licensed_matched),
                json.dumps(gate.licensed_withheld),
                None if gate.consent_given is None else int(gate.consent_given),
                int(disclaimer_shown), llm_model, error,
            ),
        )
        for act_name in gate.licensed_matched:
            self.conn.execute(
                "INSERT INTO consent_log (id, ts, query_id, act_name, granted) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), ts, query_id, act_name,
                 int(act_name not in gate.licensed_withheld)),
            )
        self.conn.commit()
        return query_id

    # ------------------------------------------------------------------
    # retrieval / retention
    # ------------------------------------------------------------------

    def get(self, query_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (query_id,)
        ).fetchone()
        return dict(row) if row else None

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]

    def purge_older_than(self, days: int) -> int:
        """Delete audit rows older than `days`. DPDP's storage-limitation
        principle expects logs to have a retention bound, not to accumulate
        forever; this makes that bound something a scheduled job can
        enforce (see the gap-5 auto-update pipeline) rather than a policy
        that exists only in a document. Returns the number of rows deleted."""
        cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).isoformat(
            timespec="seconds"
        )
        self.conn.execute(
            "DELETE FROM consent_log WHERE query_id IN "
            "(SELECT id FROM audit_log WHERE ts < ?)",
            (cutoff,),
        )
        cur = self.conn.execute("DELETE FROM audit_log WHERE ts < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount
