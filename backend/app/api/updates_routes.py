from fastapi import APIRouter, HTTPException

from ..schemas import (
    CheckNowRequest,
    CheckNowResponse,
    PublishResponse,
    ReviewDecisionRequest,
    ReviewQueueEntry,
)
from ..services.updates_service import updates_service

router = APIRouter(prefix="/updates", tags=["Updates"])


@router.get("/pending", response_model=list[ReviewQueueEntry])
def list_pending() -> list[ReviewQueueEntry]:
    """MANDATORY_REVIEW items awaiting a human's approve/reject decision."""
    return [ReviewQueueEntry(**e) for e in updates_service.pending()]


@router.get("/queued", response_model=list[ReviewQueueEntry])
def list_queued() -> list[ReviewQueueEntry]:
    """AUTO_PUBLISH / PUBLISH_THEN_AUDIT items the classifier cleared but
    that have not been ingested yet (the normal state when
    updates_auto_ingest is off)."""
    return [ReviewQueueEntry(**e) for e in updates_service.queued_for_ingest()]


@router.get("/needs-audit", response_model=list[ReviewQueueEntry])
def list_needs_audit() -> list[ReviewQueueEntry]:
    """Already-published PUBLISH_THEN_AUDIT items awaiting the
    after-the-fact human sign-off that tier promises."""
    return [ReviewQueueEntry(**e) for e in updates_service.needs_audit()]


@router.get("/history", response_model=list[ReviewQueueEntry])
def list_history(limit: int = 50) -> list[ReviewQueueEntry]:
    return [ReviewQueueEntry(**e) for e in updates_service.history(limit=limit)]


@router.post("/check-now", response_model=CheckNowResponse)
def check_now(request: CheckNowRequest) -> CheckNowResponse:
    """Run one watch cycle synchronously. Useful for a demo or an
    on-demand refresh rather than waiting for the schedule."""
    try:
        result = updates_service.check_now(auto_ingest=request.auto_ingest)
        return CheckNowResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"check-now failed: {exc}") from exc


@router.post("/{entry_id}/approve")
def approve(entry_id: str, request: ReviewDecisionRequest) -> dict:
    try:
        updates_service.approve(entry_id, decided_by=request.decided_by, notes=request.notes)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": entry_id, "status": "approved"}


@router.post("/{entry_id}/reject")
def reject(entry_id: str, request: ReviewDecisionRequest) -> dict:
    try:
        updates_service.reject(entry_id, decided_by=request.decided_by, notes=request.notes)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": entry_id, "status": "rejected"}


@router.post("/{entry_id}/clear-audit")
def clear_audit(entry_id: str, request: ReviewDecisionRequest) -> dict:
    try:
        updates_service.clear_audit(entry_id, decided_by=request.decided_by, notes=request.notes)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": entry_id, "needs_audit": False}


@router.post("/{entry_id}/publish", response_model=PublishResponse)
def publish(entry_id: str) -> PublishResponse:
    """Run the real ingestion pipeline for one approved or
    queued_for_ingest entry. This is the explicit trigger an operator
    uses when updates_auto_ingest is off (the default) — approval alone
    never silently ingests anything."""
    try:
        result = updates_service.publish_entry(entry_id)
        return PublishResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
