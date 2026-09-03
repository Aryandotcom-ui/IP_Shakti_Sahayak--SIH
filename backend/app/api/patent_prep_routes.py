from fastapi import APIRouter, HTTPException

from ..schemas import (
    CaseEventResponse,
    CaseIntakeRequest,
    CaseResponse,
    CaseStatusUpdateRequest,
    HandoffRequest,
)
from ..services.patent_prep_service import patent_prep_service

# Importing the service above already puts the repo root on sys.path, so
# this resolves the same way ai_service.py's own ai.* imports do.
from ai.patent_prep.tracker import CaseNotFound  # noqa: E402

router = APIRouter(prefix="/patent-cases", tags=["Patent Prep"])


@router.post("", response_model=dict)
def create_case(request: CaseIntakeRequest) -> dict:
    case_id = patent_prep_service.create_case(request.model_dump())
    return {"id": case_id, "status": "intake"}


@router.get("", response_model=list[CaseResponse])
def list_cases(status: str | None = None, limit: int = 100) -> list[CaseResponse]:
    return [CaseResponse(**c) for c in patent_prep_service.list_cases(status=status, limit=limit)]


@router.get("/{case_id}", response_model=CaseResponse)
def get_case(case_id: str) -> CaseResponse:
    try:
        return CaseResponse(**patent_prep_service.get_case(case_id))
    except CaseNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{case_id}/events", response_model=list[CaseEventResponse])
def get_events(case_id: str) -> list[CaseEventResponse]:
    return [CaseEventResponse(**e) for e in patent_prep_service.events(case_id)]


@router.put("/{case_id}/intake", response_model=dict)
def update_intake(case_id: str, request: CaseIntakeRequest) -> dict:
    try:
        patent_prep_service.update_intake(case_id, request.model_dump())
    except CaseNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": case_id, "status": "updated"}


@router.post("/{case_id}/precheck", response_model=dict)
def precheck(case_id: str) -> dict:
    """Runs the same ABS/prior-art screening the RAG query path uses
    (ai.compliance.assess()) against this case's intake."""
    try:
        return patent_prep_service.precheck(case_id)
    except CaseNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{case_id}/draft-forms", response_model=dict)
def draft_forms(case_id: str) -> dict:
    """Drafts Form 1 / Form 3 (and Form 27, once granted) — draft content
    for a patent agent to transcribe and verify, not a filed copy. See
    ai/patent_prep/forms.py's module docstring."""
    try:
        return patent_prep_service.draft_forms(case_id)
    except CaseNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{case_id}/deadlines", response_model=list[dict])
def deadlines(case_id: str) -> list[dict]:
    """Computed against ai/patent_prep/deadlines.yaml — several of these
    rules are review_status: draft, meaning confirm the figure before
    relying on it. See that file's header."""
    try:
        return patent_prep_service.deadlines(case_id)
    except CaseNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{case_id}/handoff", response_model=dict)
def handoff(case_id: str, request: HandoffRequest) -> dict:
    """Bundles intake + a fresh precheck + drafted forms + deadlines into
    one package and records the handoff on the case. Handoff itself
    (actually sending the package) is a manual step outside this API."""
    try:
        return patent_prep_service.handoff(case_id, recipient=request.recipient, notes=request.notes)
    except CaseNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{case_id}/status", response_model=dict)
def update_status(case_id: str, request: CaseStatusUpdateRequest) -> dict:
    """Set any status, including prosecution states this module cannot
    observe itself (filed, fer_received, granted, abandoned, refused) —
    see ai/patent_prep/tracker.py's module docstring."""
    try:
        patent_prep_service.update_status(case_id, request.status, detail=request.detail)
    except CaseNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": case_id, "status": request.status}
