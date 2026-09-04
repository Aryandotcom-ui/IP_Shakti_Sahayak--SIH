"""
ai/patent_prep/intake.py

Structured intake for one patent-preparation case.

Reuses `ai.compliance.context.ComplianceContext`'s field names verbatim
(`formulation_type` through `ingredients`) rather than inventing parallel
ones, so `precheck.py` can hand a case straight to `ai.compliance.assess()`
with no translation layer to keep in sync — the same reason
`backend/app/schemas.py`'s `ComplianceFacts` uses those exact names too.

Everything defaults to None/empty. An intake gets filled in across
several conversations with an applicant, not in one pass, and a required
field here would force guessing at facts nobody has supplied yet — the
same posture `ComplianceContext` itself takes, for the same reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# The ComplianceContext fields this intake mirrors, in the order that
# module declares them. Kept as a tuple, not re-derived from
# ComplianceContext's own dataclass fields, so this module has no import
# dependency on ai.compliance beyond precheck.py's use of it — intake.py
# stays importable on its own.
_COMPLIANCE_FIELDS = (
    "formulation_type", "source_organism", "jurisdiction",
    "applicant_category", "practitioner_is_registered_ayush",
    "resource_origin", "resource_cultivation", "uses_biological_material",
    "uses_codified_tk", "seeking_ipr", "ipr_already_granted",
    "intends_commercialisation", "formulation_name", "ingredients",
)


@dataclass
class CaseIntake:
    # -- who's asking and what for --------------------------------------
    applicant_name: Optional[str] = None
    applicant_address: Optional[str] = None
    inventors: list[str] = field(default_factory=list)
    invention_title: Optional[str] = None
    abstract: Optional[str] = None

    # -- ai.compliance.ComplianceContext fields, verbatim -----------------
    formulation_type: Optional[str] = None
    source_organism: Optional[str] = None
    jurisdiction: Optional[str] = None
    applicant_category: Optional[str] = None
    practitioner_is_registered_ayush: Optional[bool] = None
    resource_origin: Optional[str] = None
    resource_cultivation: Optional[str] = None
    uses_biological_material: Optional[bool] = None
    uses_codified_tk: Optional[bool] = None
    seeking_ipr: Optional[bool] = None
    ipr_already_granted: Optional[bool] = None
    intends_commercialisation: Optional[bool] = None
    formulation_name: Optional[str] = None
    ingredients: Optional[list[str]] = None

    # -- dates that anchor deadline tracking (see deadlines.py) -----------
    priority_date: Optional[str] = None    # ISO 8601; first filing this claims priority from
    filing_date: Optional[str] = None      # ISO 8601; this application's own filing date
    fer_issued_date: Optional[str] = None  # ISO 8601; First Examination Report issue date
    grant_date: Optional[str] = None       # ISO 8601; date of grant, if granted

    def compliance_facts(self) -> dict[str, Any]:
        """The subset of fields `ai.compliance.assess()` understands, with
        unset ones dropped rather than passed through as None. `assess()`
        treats an explicit None the same as "unknown" either way, but
        omitting the key is the more honest signal for "not asked yet"."""
        return {
            name: getattr(self, name)
            for name in _COMPLIANCE_FIELDS
            if getattr(self, name) is not None
        }

    def missing_intake_fields(self) -> list[str]:
        """Fields worth prompting for before drafting forms. Not every
        field — the compliance facts already have their own
        missing-field story via ai.compliance.context.CRITICAL_FIELDS —
        just the ones forms.py needs that ComplianceContext does not
        carry at all."""
        required = ("applicant_name", "inventors", "invention_title")
        return [f for f in required if not getattr(self, f)]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseIntake":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
