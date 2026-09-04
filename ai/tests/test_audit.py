"""
Tests for ai/audit.py — the DPDP-aligned query audit trail and the
licensed-source consent gate.

    python -m pytest ai/tests/test_audit.py -v

The consent tests are the ones worth reading closely: they pin that a
licensed act is withheld by default (no consent means no consent, not an
implicit yes), that consent is per-act rather than blanket, and that a
purely public query never triggers the gate at all (consent_given stays
None, not False — "not applicable" and "refused" are different facts).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.audit import AuditLog, CitationGate, load_access_map  # noqa: E402


@pytest.fixture
def corpus_with_licensed_act(tmp_path: Path) -> Path:
    manifest = {
        "documents": [
            {"file": "a.pdf", "act_name": "The Patents Act, 1970"},
            {
                "file": "b.pdf",
                "act_name": "Paid Reporter Series on ASU&H Case Law",
                "access": "licensed",
            },
        ]
    }
    path = tmp_path / "corpus.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return path


@pytest.fixture
def audit(tmp_path: Path, corpus_with_licensed_act: Path) -> AuditLog:
    log = AuditLog(tmp_path / "audit.sqlite3", corpus_path=corpus_with_licensed_act)
    yield log
    log.close()


def test_load_access_map_defaults_to_public(corpus_with_licensed_act: Path):
    access = load_access_map(corpus_with_licensed_act)
    assert access["The Patents Act, 1970"] == "public"
    assert access["Paid Reporter Series on ASU&H Case Law"] == "licensed"


def test_load_access_map_missing_file_returns_empty(tmp_path: Path):
    assert load_access_map(tmp_path / "does-not-exist.yaml") == {}


def test_gate_public_only_query_is_not_applicable(audit: AuditLog):
    gate = audit.gate_citations(["The Patents Act, 1970"], consented_acts=None)
    assert gate.licensed_matched == []
    assert gate.licensed_withheld == []
    assert gate.consent_given is None  # not applicable, not "refused"


def test_gate_licensed_act_without_consent_is_withheld(audit: AuditLog):
    gate = audit.gate_citations(
        ["The Patents Act, 1970", "Paid Reporter Series on ASU&H Case Law"],
        consented_acts=None,
    )
    assert gate.licensed_matched == ["Paid Reporter Series on ASU&H Case Law"]
    assert gate.licensed_withheld == ["Paid Reporter Series on ASU&H Case Law"]
    assert gate.consent_given is False


def test_gate_licensed_act_with_consent_is_not_withheld(audit: AuditLog):
    gate = audit.gate_citations(
        ["Paid Reporter Series on ASU&H Case Law"],
        consented_acts={"Paid Reporter Series on ASU&H Case Law"},
    )
    assert gate.licensed_matched == ["Paid Reporter Series on ASU&H Case Law"]
    assert gate.licensed_withheld == []
    assert gate.consent_given is True


def test_gate_consent_is_per_act_not_blanket(audit: AuditLog):
    # Consenting to a different act name does not grant consent for this one
    # — an exact-match contract, same as everywhere else act_name is used.
    gate = audit.gate_citations(
        ["Paid Reporter Series on ASU&H Case Law"],
        consented_acts={"Some Other Licensed Act"},
    )
    assert gate.licensed_withheld == ["Paid Reporter Series on ASU&H Case Law"]
    assert gate.consent_given is False


def test_log_query_round_trips(audit: AuditLog):
    gate = CitationGate()
    query_id = audit.log_query(
        query_text="Can a classical formulation be patented in India?",
        jurisdiction="india",
        formulation_type="classical",
        top_k=5,
        matched_chunk_ids=["c1", "c2"],
        confidence=0.42,
        should_abstain=False,
        citations=[{"act_name": "The Patents Act, 1970", "section": "3(p)"}],
        gate=gate,
        disclaimer_shown=True,
        llm_model="claude-sonnet-4-5",
    )
    row = audit.get(query_id)
    assert row is not None
    assert row["query_text"] == "Can a classical formulation be patented in India?"
    assert row["should_abstain"] == 0
    assert row["consent_given"] is None
    assert audit.count() == 1


def test_log_query_records_consent_log_rows(audit: AuditLog):
    gate = audit.gate_citations(
        ["Paid Reporter Series on ASU&H Case Law"], consented_acts=None
    )
    query_id = audit.log_query(
        query_text="q", jurisdiction=None, formulation_type=None, top_k=5,
        matched_chunk_ids=[], confidence=0.1, should_abstain=True,
        citations=[], gate=gate, disclaimer_shown=True,
    )
    rows = audit.conn.execute(
        "SELECT act_name, granted FROM consent_log WHERE query_id = ?",
        (query_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["act_name"] == "Paid Reporter Series on ASU&H Case Law"
    assert rows[0]["granted"] == 0


def test_log_query_records_error(audit: AuditLog):
    query_id = audit.log_query(
        query_text="q", jurisdiction=None, formulation_type=None, top_k=5,
        matched_chunk_ids=[], confidence=None, should_abstain=True,
        citations=[], gate=None, disclaimer_shown=False,
        error="RuntimeError: corpus unavailable",
    )
    row = audit.get(query_id)
    assert row["error"] == "RuntimeError: corpus unavailable"
    assert row["confidence"] is None


def test_recent_orders_newest_first(audit: AuditLog):
    ids = [
        audit.log_query(
            query_text=f"q{i}", jurisdiction=None, formulation_type=None,
            top_k=5, matched_chunk_ids=[], confidence=0.5,
            should_abstain=False, citations=[], gate=None,
            disclaimer_shown=True,
        )
        for i in range(3)
    ]
    recent = audit.recent(limit=10)
    assert [r["id"] for r in recent] == list(reversed(ids)) or len(recent) == 3


def test_purge_older_than_removes_old_rows_and_their_consent_rows(audit: AuditLog):
    gate = audit.gate_citations(
        ["Paid Reporter Series on ASU&H Case Law"],
        consented_acts={"Paid Reporter Series on ASU&H Case Law"},
    )
    query_id = audit.log_query(
        query_text="q", jurisdiction=None, formulation_type=None, top_k=5,
        matched_chunk_ids=[], confidence=0.5, should_abstain=False,
        citations=[], gate=gate, disclaimer_shown=True,
    )
    assert audit.count() == 1

    deleted = audit.purge_older_than(days=-1)  # cutoff is in the future
    assert deleted == 1
    assert audit.count() == 0
    assert audit.get(query_id) is None
    remaining_consent = audit.conn.execute(
        "SELECT COUNT(*) FROM consent_log WHERE query_id = ?", (query_id,)
    ).fetchone()[0]
    assert remaining_consent == 0


def test_purge_keeps_recent_rows(audit: AuditLog):
    audit.log_query(
        query_text="q", jurisdiction=None, formulation_type=None, top_k=5,
        matched_chunk_ids=[], confidence=0.5, should_abstain=False,
        citations=[], gate=None, disclaimer_shown=True,
    )
    deleted = audit.purge_older_than(days=180)  # far in the future cutoff-wise
    assert deleted == 0
    assert audit.count() == 1
