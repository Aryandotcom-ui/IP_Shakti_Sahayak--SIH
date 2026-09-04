"""
ai/patent_prep/forms.py

Drafts the field content for the Indian Patent Office forms a case is
most likely to need — Form 1 (application), Form 3 (foreign-filing
declaration), Form 27 (statement of working) — from a case's intake.

What this is not
------------------
Not a filled copy of the official form. This module has no access to
the IPO's actual form layout (ai/corpus.yaml lists patents-rules-2003.pdf
as `status: pending` — not yet ingested — for exactly this reason: Form
1/3/27's exact field mechanics need that source). A `FormDraft` is
structured content plus a plain-text rendering meant for a patent agent
to transcribe onto the real form and verify, not to file directly. Every
draft carries `caveats` saying so; treat that list as load-bearing, not
boilerplate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .intake import CaseIntake

_STANDARD_CAVEAT = (
    "Draft content only — transcribe onto the official IPO form and have "
    "a registered patent agent verify every field before filing. This "
    "module does not have the official form layout (see ai/corpus.yaml's "
    "patents-rules-2003.pdf entry, status: pending)."
)


@dataclass
class FormDraft:
    form_id: str
    title: str
    fields: dict[str, Any]
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "form_id": self.form_id, "title": self.title,
            "fields": self.fields, "caveats": self.caveats,
            "rendered_text": self.render(),
        }

    def render(self) -> str:
        lines = [f"DRAFT — {self.title} ({self.form_id})", "=" * 60, ""]
        for key, value in self.fields.items():
            label = key.replace("_", " ").title()
            if isinstance(value, list):
                lines.append(f"{label}:")
                lines.extend(f"  - {v}" for v in (value or ["(none supplied)"]))
            else:
                lines.append(f"{label}: {value if value not in (None, '') else '[NOT SUPPLIED]'}")
        lines.append("")
        lines.append("-" * 60)
        lines.append("CAVEATS")
        lines.extend(f"  - {c}" for c in self.caveats)
        return "\n".join(lines)


def draft_form_1(case: CaseIntake) -> FormDraft:
    """Form 1 — Application for Grant of Patent."""
    claims_earlier_priority = bool(case.priority_date) and case.priority_date != case.filing_date
    application_category = "convention" if claims_earlier_priority else "ordinary"
    fields = {
        "title_of_invention": case.invention_title,
        "applicant_name": case.applicant_name,
        "applicant_address": case.applicant_address,
        "applicant_category": case.applicant_category,
        "inventors": list(case.inventors),
        "application_category_guess": application_category,
        "priority_date_claimed": case.priority_date,
        "abstract": case.abstract,
    }
    caveats = [_STANDARD_CAVEAT]
    if case.missing_intake_fields():
        caveats.append(
            "Incomplete intake: " + ", ".join(case.missing_intake_fields())
        )
    if not case.priority_date:
        caveats.append(
            "No priority_date supplied — application_category_guess assumes "
            "an ordinary application. Confirm with the applicant whether "
            "this claims priority from an earlier filing."
        )
    return FormDraft(form_id="Form 1", title="Application for Grant of Patent",
                      fields=fields, caveats=caveats)


def draft_form_3(case: CaseIntake) -> FormDraft:
    """Form 3 — Statement and Undertaking under Section 8.

    Section 8 requires disclosure of corresponding foreign applications.
    This module has no source of the applicant's actual foreign-filing
    history — the field is left for the applicant/agent to supply, never
    inferred or defaulted to "none"."""
    fields = {
        "applicant_name": case.applicant_name,
        "invention_title": case.invention_title,
        "corresponding_foreign_applications": (
            "[APPLICANT MUST SUPPLY — not inferable from intake]"
        ),
        "undertaking_to_keep_office_informed": (
            "Standard undertaking to inform the Controller of any "
            "corresponding foreign application filed after this statement, "
            "per section 8(1)."
        ),
    }
    caveats = [
        _STANDARD_CAVEAT,
        "Section 8 disclosure is a strict-liability requirement — an "
        "incomplete or false statement here can be independently fatal to "
        "the patent regardless of the invention's merits. Never file this "
        "form with a guessed or omitted foreign-filing history.",
    ]
    return FormDraft(form_id="Form 3",
                      title="Statement and Undertaking under Section 8",
                      fields=fields, caveats=caveats)


def draft_form_27(case: CaseIntake, *, financial_year: str | None = None) -> FormDraft:
    """Form 27 — Statement Regarding the Working of the Patented Invention.

    Only meaningful post-grant. `financial_year` is left for the caller
    to supply (e.g. from the current deadline computation) rather than
    guessed from today's date, since the correct year is whichever cycle
    the deadline tracker's form_27_working_statement rule is currently
    due for.
    """
    fields = {
        "patent_title": case.invention_title,
        "patentee_name": case.applicant_name,
        "financial_year": financial_year or "[SUPPLY FROM DEADLINE TRACKING]",
        "worked_in_india": "[APPLICANT MUST SUPPLY]",
        "approximate_revenue_from_working": "[APPLICANT MUST SUPPLY, IF WORKED]",
        "if_not_worked_reasons": "[APPLICANT MUST SUPPLY, IF NOT WORKED]",
    }
    caveats = [
        _STANDARD_CAVEAT,
        "Only file once the patent has actually been granted "
        "(case.grant_date set) — this draft does not check that itself.",
        "The Patents (Amendment) Rules, 2024 is understood to have changed "
        "the filing cadence to once every 3 financial years — see "
        "ai/patent_prep/deadlines.yaml's form_27_working_statement rule "
        "(review_status: draft) before relying on the cadence assumed here.",
    ]
    if not case.grant_date:
        caveats.append("case.grant_date is not set — this patent may not be granted yet.")
    return FormDraft(form_id="Form 27",
                      title="Statement Regarding the Working of the Patented Invention",
                      fields=fields, caveats=caveats)


def draft_all(case: CaseIntake) -> dict[str, FormDraft]:
    drafts = {"form_1": draft_form_1(case), "form_3": draft_form_3(case)}
    if case.grant_date:
        drafts["form_27"] = draft_form_27(case)
    return drafts
