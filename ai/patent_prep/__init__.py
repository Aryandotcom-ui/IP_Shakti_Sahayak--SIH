"""
ai/patent_prep — patent preparation and tracking.

A separate module from the RAG core: it drafts and screens, and never
touches retrieval or the corpus itself.

    intake -> precheck (ABS/TKDL, via ai.compliance) -> draft forms
        -> deadline tracking -> handoff to a registered patent agent

    from ai.patent_prep import CaseIntake, CaseTracker, run_prechecks
    from ai.patent_prep import draft_all, compute_deadlines, handoff_case
"""

from .deadlines import DeadlineRule, DeadlineStatus, compute_deadlines, load_deadline_rules
from .forms import FormDraft, draft_all, draft_form_1, draft_form_3, draft_form_27
from .handoff import build_handoff_package, handoff_case
from .intake import CaseIntake
from .precheck import PrecheckReport, run_prechecks
from .tracker import CaseNotFound, CaseTracker

__all__ = [
    "CaseIntake",
    "PrecheckReport",
    "run_prechecks",
    "FormDraft",
    "draft_all",
    "draft_form_1",
    "draft_form_3",
    "draft_form_27",
    "DeadlineRule",
    "DeadlineStatus",
    "compute_deadlines",
    "load_deadline_rules",
    "CaseTracker",
    "CaseNotFound",
    "build_handoff_package",
    "handoff_case",
]
