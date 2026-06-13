from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.discovery import DiscoveryCandidate
from app.schemas.auth import CurrentUser
from app.schemas.discovery import DiscoveryCandidateRead, DiscoveryImportRequest, DiscoveryImportResult, DiscoverySummaryRead
from app.services.discovery_service import (
    approve_candidate,
    auto_add_recommended_candidates,
    candidate_to_dict,
    discovery_summary,
    evaluate_candidates,
    import_candidates_from_csv,
    import_candidates_from_text,
    run_wallet_discovery,
)


router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/summary", response_model=DiscoverySummaryRead)
def summary(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return discovery_summary(db)


@router.post("/run", response_model=DiscoverySummaryRead)
def run_discovery(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return run_wallet_discovery(db)


@router.post("/evaluate")
def evaluate(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return {"evaluated": evaluate_candidates(db)}


@router.post("/import", response_model=DiscoveryImportResult)
def import_candidates(
    payload: DiscoveryImportRequest,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    source_name = payload.source_name or payload.source_type
    if payload.source_type.lower() == "csv":
        return import_candidates_from_csv(db, payload.content, source_name)
    return import_candidates_from_text(db, payload.content, source_name)


@router.post("/candidates/{candidate_id}/approve")
def approve(
    candidate_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        wallet = approve_candidate(db, candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"wallet_id": wallet.id, "address": wallet.address}


@router.post("/auto-add")
def auto_add(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return {"added": auto_add_recommended_candidates(db)}


@router.get("/candidates/{candidate_id}", response_model=DiscoveryCandidateRead)
def get_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    candidate = db.get(DiscoveryCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Discovery candidate not found")
    return candidate_to_dict(candidate)
