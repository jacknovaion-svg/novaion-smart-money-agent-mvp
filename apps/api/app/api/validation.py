from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.schemas.auth import CurrentUser
from app.services.health_service import system_health
from app.services.ops_service import validation_dashboard, validation_readiness


router = APIRouter(prefix="/validation", tags=["validation"])


@router.get("/readiness")
def readiness(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    health = system_health(db)
    return validation_readiness(db, health)


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return validation_dashboard(db)
