"""ABS-compliance screening and prior-art probing.

Public entry point:

    from ai.compliance import assess

    report = assess(classification, applicant_category="foreign_national",
                    resource_origin="india", seeking_ipr=True)
    report.to_dict()
"""

from .abs import ABSAssessor, ComplianceReport, ObligationView, get_assessor
from .context import ComplianceContext, question_for
from .tkdl import (
    LocalClassicalProbe,
    NullProbe,
    PriorArtHit,
    PriorArtProbe,
    ProbeResult,
    TKDLProbe,
    get_probe,
)


def assess(classification=None, *, corpus_path: str | None = None, **facts) -> ComplianceReport:
    """Screen a classification plus known facts against the regulatory graph."""
    return get_assessor(corpus_path).assess_from_classification(classification, **facts)


__all__ = [
    "ABSAssessor",
    "ComplianceContext",
    "ComplianceReport",
    "LocalClassicalProbe",
    "NullProbe",
    "ObligationView",
    "PriorArtHit",
    "PriorArtProbe",
    "ProbeResult",
    "TKDLProbe",
    "assess",
    "get_assessor",
    "get_probe",
    "question_for",
]
