from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.services.v3_reporting import dashboard

router = APIRouter(
    prefix="/v3", tags=["v3-simulation"], dependencies=[Depends(get_current_user)]
)


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    return dashboard(db)


@router.get("/attribution")
def get_attribution(db: Session = Depends(get_db)):
    return dashboard(db).get("attribution", {})


@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    data = dashboard(db)
    return {
        key: data.get(key)
        for key in (
            "enabled",
            "version",
            "cutover_at",
            "started_at",
            "end_at",
            "simulation_only",
            "scheduler",
            "quality",
        )
    }
