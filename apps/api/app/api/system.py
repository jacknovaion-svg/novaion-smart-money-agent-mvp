from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.system_log import SystemLog
from app.schemas.auth import CurrentUser
from app.schemas.system_log import SystemLogRead
from app.services.health_service import system_health


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/logs", response_model=list[SystemLogRead])
def list_logs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[SystemLog]:
    return db.query(SystemLog).order_by(SystemLog.created_at.desc()).limit(limit).all()


@router.get("/health")
def health_center(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return system_health(db)
