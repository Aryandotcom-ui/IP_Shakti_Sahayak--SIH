"""
ai/patent_prep/precheck.py

Runs the same ABS/prior-art screening the RAG query path uses
(`ai.compliance.assess()`) against a case's intake, and adds the one
judgement patent_prep needs on top: is this case clear to move to
drafting forms, or is something still outstanding.

No obligation logic is duplicated here. `ai.compliance.assess()` already
runs the TKDL prior-art probe automatically when an obligation requests
it — the `probe: tkdl` marker on the section 3(p) node in
ontology.yaml — so calling it once gets both the ABS screening and the
prior-art check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..compliance import ComplianceReport, assess
from .intake import CaseIntake


@dataclass
class PrecheckReport:
    compliance: ComplianceReport
    blocking: list[str] = field(default_factory=list)
    critical_open_questions: list[str] = field(default_factory=list)
    clear_to_draft: bool = False
    reasons_not_clear: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compliance": self.compliance.to_dict(),
            "blocking": self.blocking,
            "critical_open_questions": self.critical_open_questions,
            "clear_to_draft": self.clear_to_draft,
            "reasons_not_clear": self.reasons_not_clear,
        }


def run_prechecks(case: CaseIntake, *, corpus_path: str | None = None) -> PrecheckReport:
    """Screen a case's known facts and decide whether drafting can start.

    "Clear to draft" is deliberately conservative: any blocking
    obligation, any critical open question, or missing intake basics
    (applicant name, inventors, invention title — forms.py cannot draft
    without them) holds the case back. A patent agent can still choose to
    draft anyway with an incomplete precheck; this function's job is to
    make that an informed choice, not to gate the workflow outright.
    """
    report = assess(None, corpus_path=corpus_path, **case.compliance_facts())

    blocking = [o.label for o in report.blocking]
    critical_questions = [
        q["question"] for q in report.open_questions if q.get("importance") == "critical"
    ]

    reasons: list[str] = []
    if blocking:
        reasons.append(f"{len(blocking)} obligation(s) block grant until discharged")
    if critical_questions:
        reasons.append(f"{len(critical_questions)} critical compliance question(s) unanswered")
    missing_intake = case.missing_intake_fields()
    if missing_intake:
        reasons.append(f"intake incomplete: {', '.join(missing_intake)}")

    return PrecheckReport(
        compliance=report,
        blocking=blocking,
        critical_open_questions=critical_questions,
        clear_to_draft=not reasons,
        reasons_not_clear=reasons,
    )
