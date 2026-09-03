"""
ai/patent_prep/tracker.py

SQLite-backed case tracking. Same registry pattern as ai/store.py,
ai/audit.py, and ai/updates/queue.py: one file, one schema, one class.

`status` tracks how far case preparation has gotten, not prosecution
outcome — this module drafts and screens, it does not file anything. The
statuses it manages are `intake` -> `prechecked` -> `drafted` ->
`handed_off`. Anything past that (filed, fer_received, granted,
abandoned, refused) happens outside this system once a patent agent has
the case, and `update_status()` accepts any string so the case record
can still reflect it — the point is this module does not pretend to
authoritatively track IPO prosecution state it has no way to observe.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .intake import CaseIntake

log = logging.getLogger(__name__)

_MANAGED_STATUSES = ("intake", "prechecked", "drafted", "handed_off")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id              TEXT PRIMARY KEY,
    intake          TEXT NOT NULL,   -- JSON CaseIntake.to_dict()
    status          TEXT NOT NULL,
    precheck_result TEXT,            -- JSON PrecheckReport.to_dict(), set by record_precheck
    forms_result    TEXT,            -- JSON {form_id: FormDraft.to_dict()}, set by record_forms
    handoff_result  TEXT,            -- JSON handoff package, set by record_handoff
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);

CREATE TABLE IF NOT EXISTS case_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT NOT NULL,
    ts         TEXT NOT NULL,
    event      TEXT NOT NULL,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_case ON case_events(case_id);
"""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class CaseNotFound(Exception):
    pass


class CaseTracker:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "CaseTracker":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _log_event(self, case_id: str, event: str, detail: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO case_events (case_id, ts, event, detail) VALUES (?, ?, ?, ?)",
            (case_id, _now(), event, detail),
        )

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def create_case(self, intake: CaseIntake) -> str:
        case_id = str(uuid.uuid4())
        now = _now()
        self.conn.execute(
            "INSERT INTO cases (id, intake, status, created_at, updated_at) "
            "VALUES (?, ?, 'intake', ?, ?)",
            (case_id, json.dumps(intake.to_dict()), now, now),
        )
        self._log_event(case_id, "created")
        self.conn.commit()
        return case_id

    def update_intake(self, case_id: str, intake: CaseIntake) -> None:
        self._require(case_id)
        self.conn.execute(
            "UPDATE cases SET intake = ?, updated_at = ? WHERE id = ?",
            (json.dumps(intake.to_dict()), _now(), case_id),
        )
        self._log_event(case_id, "intake_updated")
        self.conn.commit()

    def record_precheck(self, case_id: str, precheck_dict: dict[str, Any]) -> None:
        self._require(case_id)
        self.conn.execute(
            "UPDATE cases SET precheck_result = ?, status = 'prechecked', "
            "updated_at = ? WHERE id = ?",
            (json.dumps(precheck_dict), _now(), case_id),
        )
        self._log_event(case_id, "prechecked",
                         detail=f"clear_to_draft={precheck_dict.get('clear_to_draft')}")
        self.conn.commit()

    def record_forms(self, case_id: str, forms_dict: dict[str, Any]) -> None:
        self._require(case_id)
        self.conn.execute(
            "UPDATE cases SET forms_result = ?, status = 'drafted', "
            "updated_at = ? WHERE id = ?",
            (json.dumps(forms_dict), _now(), case_id),
        )
        self._log_event(case_id, "forms_drafted", detail=",".join(forms_dict.keys()))
        self.conn.commit()

    def record_handoff(
        self, case_id: str, handoff_dict: dict[str, Any], *, recipient: str, notes: str | None = None
    ) -> None:
        self._require(case_id)
        self.conn.execute(
            "UPDATE cases SET handoff_result = ?, status = 'handed_off', "
            "updated_at = ? WHERE id = ?",
            (json.dumps(handoff_dict), _now(), case_id),
        )
        self._log_event(case_id, "handed_off", detail=f"recipient={recipient} notes={notes}")
        self.conn.commit()

    def update_status(self, case_id: str, status: str, *, detail: str | None = None) -> None:
        """Set any status string, including ones this module does not
        manage (filed, fer_received, granted, abandoned, refused, ...) —
        see the module docstring for why those are left open rather than
        enumerated."""
        self._require(case_id)
        self.conn.execute(
            "UPDATE cases SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), case_id),
        )
        self._log_event(case_id, "status_changed", detail=detail or status)
        self.conn.commit()

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def _require(self, case_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise CaseNotFound(f"no case {case_id!r}")
        return row

    def get_case(self, case_id: str) -> dict[str, Any]:
        row = self._require(case_id)
        return self._row_to_dict(row)

    def get_intake(self, case_id: str) -> CaseIntake:
        row = self._require(case_id)
        return CaseIntake.from_dict(json.loads(row["intake"]))

    def list_cases(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM cases WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM cases ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def events(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT ts, event, detail FROM case_events WHERE case_id = ? ORDER BY ts ASC",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["intake"] = json.loads(d["intake"])
        for key in ("precheck_result", "forms_result", "handoff_result"):
            if d.get(key):
                d[key] = json.loads(d[key])
        return d
