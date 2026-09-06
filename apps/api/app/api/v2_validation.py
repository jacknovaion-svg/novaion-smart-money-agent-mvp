from fastapi import APIRouter, Depends, HTTPException
from app.core.config import get_settings
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.signal import Signal
from app.models.v2_validation import ShadowTrade
from app.schemas.auth import CurrentUser
from app.services.v2_validation_service import (
    alpha_attribution,
    equity_curve,
    max_drawdown,
    record_equity_snapshot,
    close_shadow_trade,
    create_shadow_trade,
    shadow_summary,
)


router = APIRouter(prefix="/v2-validation", tags=["v2-validation"])


@router.post("/equity-snapshots")
def create_equity_snapshot(db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    _legacy_write_guard()
    row = record_equity_snapshot(db)
    return {"id": row.id, "captured_at": row.captured_at, "equity": row.equity}


@router.get("/equity-curve")
def get_equity_curve(db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    curve = equity_curve(db)
    return {"curve": curve, "max_drawdown": max_drawdown(curve)}


@router.get("/alpha-attribution")
def get_alpha_attribution(db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    return alpha_attribution(db)


@router.get("/shadow-summary")
def get_shadow_summary(db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    return shadow_summary(db)


@router.post("/shadow-trades/{signal_id}")
def open_shadow_trade(signal_id: int, db: Session = Depends(get_db), _user: CurrentUser = Depends(get_current_user)):
    _legacy_write_guard()
    signal = db.query(Signal).filter(Signal.id == signal_id).first()
    if not signal:
        return {"detail": "Signal not found"}
    trade = create_shadow_trade(db, signal)
    return {"id": trade.id, "signal_id": trade.signal_id, "status": trade.status, "entry_price": trade.entry_price}


@router.post("/shadow-trades/{trade_id}/close")
def close_shadow_trade_endpoint(
    trade_id: int,
    payload: dict[str, float],
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    _legacy_write_guard()
    trade = db.query(ShadowTrade).filter(ShadowTrade.id == trade_id).first()
    if not trade:
        return {"detail": "Shadow trade not found"}
    closed = close_shadow_trade(db, trade, float(payload.get("exit_price", 0)))
    return {"id": closed.id, "status": closed.status, "net_pnl": closed.net_pnl}


def _legacy_write_guard():
    if get_settings().v3_enabled:
        raise HTTPException(status_code=409, detail="V2 Shadow is archived; V3 is forward-only and scheduler-owned")
