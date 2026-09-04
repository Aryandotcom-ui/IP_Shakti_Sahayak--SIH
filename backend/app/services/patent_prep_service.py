from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.patent_prep.deadlines import compute_deadlines  # noqa: E402
from ai.patent_prep.forms import draft_all  # noqa: E402
from ai.patent_prep.handoff import handoff_case as run_handoff  # noqa: E402
from ai.patent_prep.intake import CaseIntake  # noqa: E402
from ai.patent_prep.precheck import run_prechecks  # noqa: E402
from ai.patent_prep.tracker import CaseTracker  # noqa: E402

from ..config import settings  # noqa: E402


class PatentPrepService:
    """Application-facing adapter around ai/patent_prep — same relationship
    to that module as AIService has to ai/ and UpdatesService has to
    ai/updates: converts HTTP input into ai/patent_prep calls and back,
    without owning any of the intake/precheck/drafting/deadline logic
    itself."""

    def __init__(self) -> None:
        self._tracker: CaseTracker | None = None

    @property
    def tracker(self) -> CaseTracker:
        if self._tracker is None:
            self._tracker = CaseTracker(settings.patent_cases_db_path)
        return self._tracker

    def create_case(self, intake_dict: dict[str, Any]) -> str:
        case = CaseIntake.from_dict(intake_dict)
        return self.tracker.create_case(case)

    def update_intake(self, case_id: str, intake_dict: dict[str, Any]) -> None:
        case = CaseIntake.from_dict(intake_dict)
        self.tracker.update_intake(case_id, case)

    def get_case(self, case_id: str) -> dict[str, Any]:
        return self.tracker.get_case(case_id)

    def list_cases(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.tracker.list_cases(status=status, limit=limit)

    def events(self, case_id: str) -> list[dict[str, Any]]:
        return self.tracker.events(case_id)

    def precheck(self, case_id: str) -> dict[str, Any]:
        case = self.tracker.get_intake(case_id)
        report = run_prechecks(case, corpus_path=settings.corpus_manifest_path)
        result = report.to_dict()
        self.tracker.record_precheck(case_id, result)
        return result

    def draft_forms(self, case_id: str) -> dict[str, Any]:
        case = self.tracker.get_intake(case_id)
        forms = draft_all(case)
        result = {form_id: draft.to_dict() for form_id, draft in forms.items()}
        self.tracker.record_forms(case_id, result)
        return result

    def deadlines(self, case_id: str) -> list[dict[str, Any]]:
        case = self.tracker.get_intake(case_id)
        return [d.to_dict() for d in compute_deadlines(case)]

    def handoff(self, case_id: str, *, recipient: str, notes: str | None = None) -> dict[str, Any]:
        return run_handoff(
            self.tracker, case_id, recipient=recipient, notes=notes,
            corpus_path=settings.corpus_manifest_path,
        )

    def update_status(self, case_id: str, status: str, *, detail: str | None = None) -> None:
        self.tracker.update_status(case_id, status, detail=detail)


patent_prep_service = PatentPrepService()
