"""
ai/patent_prep/handoff.py

Bundles a case's intake, pre-check screening, drafted forms, and current
deadline status into one package for a registered patent agent to take
over.

Handoff itself is a manual step — an operator sends this package however
they already communicate with their agent. This module's job is to make
that package complete and to record on the case that the handoff
happened (see `CaseTracker.record_handoff`), not to deliver it anywhere.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from .deadlines import compute_deadlines
from .forms import draft_all
from .intake import CaseIntake
from .precheck import PrecheckReport, run_prechecks
from .tracker import CaseTracker


def build_handoff_package(
    case: CaseIntake,
    *,
    precheck: PrecheckReport | None = None,
    corpus_path: str | None = None,
    as_of: _dt.date | None = None,
) -> dict[str, Any]:
    """Assemble everything a patent agent needs to pick this case up.
    Runs prechecks fresh if not supplied — a handoff package built
    against a stale screening is worse than one that costs an extra
    call."""
    precheck = precheck or run_prechecks(case, corpus_path=corpus_path)
    forms = draft_all(case)
    deadlines = compute_deadlines(case, as_of=as_of)

    return {
        "generated_at": (as_of or _dt.date.today()).isoformat(),
        "intake": case.to_dict(),
        "precheck": precheck.to_dict(),
        "forms": {form_id: draft.to_dict() for form_id, draft in forms.items()},
        "deadlines": [d.to_dict() for d in deadlines],
        "handoff_notes": [
            "This package is a preparation aid, not a legal opinion.",
            "Every form draft, compliance obligation, and deadline here "
            "needs the receiving agent's independent verification before "
            "being relied on or filed.",
        ],
    }


def handoff_case(
    tracker: CaseTracker,
    case_id: str,
    *,
    recipient: str,
    notes: str | None = None,
    corpus_path: str | None = None,
    as_of: _dt.date | None = None,
) -> dict[str, Any]:
    """Build the handoff package for a tracked case and record the
    handoff on it. Returns the package."""
    case = tracker.get_intake(case_id)
    package = build_handoff_package(case, corpus_path=corpus_path, as_of=as_of)
    tracker.record_handoff(case_id, package, recipient=recipient, notes=notes)
    return package
