from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.signal import PaperTrade, Signal
from app.models.wallet import Wallet
from app.schemas.auth import CurrentUser
from app.schemas.signal import PaperAccountSummary, PaperTradeRead, SignalRead, SignalUpdate
from app.services.paper_trading_service import (
    add_signal_to_paper,
    close_from_signal,
    close_paper_trade,
    paper_account_summary,
)


router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=list[SignalRead])
def list_signals(
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[SignalRead]:
    query = db.query(Signal, Wallet).join(Wallet, Wallet.id == Signal.wallet_id)
    if status:
        query = query.filter(Signal.status == status)
    rows = query.order_by(Signal.created_at.desc()).limit(200).all()
    return [_signal_read(signal, wallet) for signal, wallet in rows]


@router.get("/paper/trades", response_model=list[PaperTradeRead])
def paper_trades(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[PaperTrade]:
    return db.query(PaperTrade).order_by(PaperTrade.opened_at.desc()).limit(200).all()


@router.post("/paper/trades/{trade_id}/close", response_model=PaperTradeRead)
def close_trade(
    trade_id: int,
    exit_price: Optional[float] = Query(default=None),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> PaperTrade:
    trade = db.get(PaperTrade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Paper trade not found")
    return close_paper_trade(db, trade, exit_price)


@router.get("/paper/summary", response_model=PaperAccountSummary)
def paper_summary(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return paper_account_summary(db)


@router.get("/{signal_id}", response_model=SignalRead)
def get_signal(
    signal_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> SignalRead:
    row = db.query(Signal, Wallet).join(Wallet, Wallet.id == Signal.wallet_id).filter(Signal.id == signal_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Signal not found")
    signal, wallet = row
    return _signal_read(signal, wallet)


@router.patch("/{signal_id}", response_model=SignalRead)
def update_signal(
    signal_id: int,
    payload: SignalUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> SignalRead:
    signal = db.get(Signal, signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    if payload.status not in {"new", "ignored", "simulated", "approved", "executed", "failed", "read"}:
        raise HTTPException(status_code=400, detail="Invalid signal status")
    signal.status = payload.status
    db.commit()
    wallet = db.get(Wallet, signal.wallet_id)
    return _signal_read(signal, wallet)


@router.post("/{signal_id}/simulate", response_model=PaperTradeRead)
def simulate_signal(
    signal_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> PaperTrade:
    signal = db.get(Signal, signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    try:
        if signal.signal_type == "close":
            closed = close_from_signal(db, signal)
            if not closed:
                raise ValueError("No open paper position to close")
            trade = (
                db.query(PaperTrade)
                .filter(PaperTrade.symbol == signal.symbol, PaperTrade.status == "closed")
                .order_by(PaperTrade.closed_at.desc())
                .first()
            )
            return trade
        return add_signal_to_paper(db, signal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _signal_read(signal: Signal, wallet: Optional[Wallet]) -> SignalRead:
    return SignalRead(
        id=signal.id,
        wallet_id=signal.wallet_id,
        platform=signal.platform,
        symbol=signal.symbol,
        signal_type=signal.signal_type,
        side=signal.side,
        source_size=signal.source_size,
        source_leverage=signal.source_leverage,
        source_entry_price=signal.source_entry_price,
        current_price=signal.current_price,
        confidence_score=signal.confidence_score,
        risk_score=signal.risk_score,
        suggested_action=signal.suggested_action,
        suggested_size_usd=signal.suggested_size_usd,
        reason=signal.reason,
        status=signal.status,
        source_trade_id=signal.source_trade_id,
        created_at=signal.created_at,
        wallet_name=wallet.name if wallet else None,
        wallet_tags=wallet.tags if wallet else None,
    )
