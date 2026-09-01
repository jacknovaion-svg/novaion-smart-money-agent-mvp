from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.signal import PaperTrade, Signal
from app.models.wallet import Wallet
from app.core.config import get_settings
from app.services.paper_account_service import paper_funds_check, requested_paper_margin
from app.services.system_log_service import write_log


STARTING_BALANCE = 1000.0
DEFAULT_SIZE_USD = 20.0


def add_signal_to_paper(db: Session, signal: Signal) -> PaperTrade:
    if signal.risk_score > 80:
        signal.status = "ignored"
        db.commit()
        raise ValueError("Risk score is above 80; skipped by paper trading rules")
    if signal.signal_type == "close" or signal.side == "close":
        raise ValueError("Close signals should close existing paper trades, not open new ones")

    existing = (
        db.query(PaperTrade)
        .filter(
            PaperTrade.wallet_id == signal.wallet_id,
            PaperTrade.symbol == signal.symbol,
            PaperTrade.side == signal.side,
            PaperTrade.status == "open",
        )
        .first()
    )
    if existing:
        signal.status = "simulated"
        db.commit()
        return existing

    leverage = _paper_leverage(signal.source_leverage)
    size_usd = requested_paper_margin(signal.suggested_size_usd)
    funds = paper_funds_check(db, size_usd)
    if not funds["allowed"]:
        signal.status = "ignored"
        db.add(signal)
        db.commit()
        write_log(
            db,
            level="info",
            module="paper_trading",
            message="insufficient_paper_funds",
            payload={
                "signal_id": signal.id,
                "wallet_id": signal.wallet_id,
                "symbol": signal.symbol,
                "action": "insufficient_paper_funds",
                "paper_trade_id": None,
                **funds,
            },
        )
        raise ValueError("Insufficient paper funds")
    raw_price = signal.current_price or signal.source_entry_price
    if raw_price <= 0:
        raise ValueError("Signal has no usable price")
    price = _entry_price(signal.side, raw_price)
    trade = PaperTrade(
        signal_id=signal.id,
        wallet_id=signal.wallet_id,
        symbol=signal.symbol,
        side=signal.side,
        entry_price=price,
        mark_price=raw_price,
        size_usd=size_usd,
        leverage=leverage,
        stop_loss=_stop_loss(signal.side, price),
        take_profit=_take_profit(signal.side, price),
        status="open",
    )
    db.add(trade)
    signal.status = "simulated"
    db.commit()
    db.refresh(trade)
    write_log(
        db,
        level="info",
        module="paper_trading",
        message="Paper trade opened",
        payload={"trade_id": trade.id, "signal_id": signal.id},
    )
    return trade


def close_paper_trade(db: Session, trade: PaperTrade, exit_price: Optional[float] = None) -> PaperTrade:
    if trade.status != "open":
        write_log(
            db,
            level="info",
            module="paper_trading",
            message="Paper trade already closed",
            payload={"trade_id": trade.id, "action": "already_closed"},
        )
        return trade
    raw_exit = exit_price or trade.exit_price or trade.entry_price
    price = _exit_price(trade.side, raw_exit)
    trade.exit_price = price
    close_raw_pnl = _calculate_raw_pnl(trade, price)
    close_fees = _fees(trade, price)
    close_slippage_adjustment = _calculate_raw_pnl(trade, raw_exit) - close_raw_pnl
    trade.raw_pnl = round((trade.raw_pnl or 0) + close_raw_pnl, 6)
    trade.fees = round((trade.fees or 0) + close_fees, 6)
    trade.slippage_adjustment = round((trade.slippage_adjustment or 0) + close_slippage_adjustment, 6)
    trade.net_pnl = round((trade.net_pnl or 0) + close_raw_pnl - close_fees, 6)
    trade.pnl = trade.net_pnl
    trade.size_usd = 0
    trade.mark_price = raw_exit
    trade.unrealized_pnl = 0
    trade.unrealized_pnl_pct = 0
    trade.status = "closed"
    trade.closed_at = datetime.now(timezone.utc)
    trade.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trade)
    write_log(
        db,
        level="info",
        module="paper_trading",
        message="Paper trade closed",
        payload={"trade_id": trade.id, "pnl": trade.pnl},
    )
    return trade


def close_from_signal(db: Session, signal: Signal) -> int:
    if signal.signal_type != "close":
        return 0
    trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.wallet_id == signal.wallet_id, PaperTrade.symbol == signal.symbol, PaperTrade.status == "open")
        .all()
    )
    for trade in trades:
        close_paper_trade(db, trade, signal.current_price or signal.source_entry_price)
    if trades:
        signal.status = "simulated"
        db.commit()
    return len(trades)


def paper_account_summary(db: Session) -> Dict:
    trades = db.query(PaperTrade).order_by(PaperTrade.opened_at.asc()).all()
    realized_pnl = sum(trade.pnl for trade in trades)
    open_unrealized = sum(
        trade.unrealized_pnl if trade.mark_price else _calculate_pnl(trade, trade.exit_price or trade.entry_price)
        for trade in trades
        if trade.status == "open"
    )
    closed = [trade for trade in trades if trade.status == "closed"]
    wins = [trade for trade in closed if trade.pnl > 0]
    today = datetime.now(timezone.utc).date()
    today_pnl = sum(
        trade.pnl
        for trade in closed
        if trade.closed_at and _as_utc(trade.closed_at).date() == today
    )
    wallet_pnl = _wallet_pnl(db, closed)
    recent = db.query(PaperTrade).order_by(PaperTrade.opened_at.desc()).limit(10).all()
    return {
        "starting_balance": STARTING_BALANCE,
        "current_equity": round(STARTING_BALANCE + realized_pnl + open_unrealized, 6),
        "today_pnl": round(today_pnl, 6),
        "total_pnl": round(realized_pnl + open_unrealized, 6),
        "win_rate": round((len(wins) / len(closed) * 100) if closed else 0, 2),
        "max_drawdown": _max_drawdown(closed),
        "open_positions": len([trade for trade in trades if trade.status == "open"]),
        "closed_trades": len(closed),
        "best_wallet": wallet_pnl["best"],
        "worst_wallet": wallet_pnl["worst"],
        "recent_trades": recent,
    }


def _paper_leverage(source_leverage: float) -> float:
    if source_leverage > 10:
        return 3.0
    return max(1.0, min(source_leverage or 1.0, 3.0))


def _stop_loss(side: str, price: float) -> float:
    return round(price * (0.97 if side == "long" else 1.03), 8)


def _take_profit(side: str, price: float) -> float:
    return round(price * (1.06 if side == "long" else 0.94), 8)


def _calculate_pnl(trade: PaperTrade, exit_price: float) -> float:
    raw_pnl = _calculate_raw_pnl(trade, _exit_price(trade.side, exit_price))
    return round(raw_pnl - _fees(trade, exit_price), 6)


def _calculate_raw_pnl(trade: PaperTrade, exit_price: float) -> float:
    return _calculate_raw_pnl_for_size(trade, exit_price, trade.size_usd)


def _calculate_raw_pnl_for_size(trade: PaperTrade, exit_price: float, size_usd: float) -> float:
    if trade.entry_price <= 0:
        return 0.0
    direction = 1 if trade.side == "long" else -1
    change = (exit_price - trade.entry_price) / trade.entry_price
    return round(size_usd * trade.leverage * change * direction, 6)


def _entry_price(side: str, price: float) -> float:
    slippage = get_settings().paper_slippage_rate
    return round(price * (1 + slippage if side == "long" else 1 - slippage), 8)


def _exit_price(side: str, price: float) -> float:
    slippage = get_settings().paper_slippage_rate
    return round(price * (1 - slippage if side == "long" else 1 + slippage), 8)


def _fees(trade: PaperTrade, exit_price: float) -> float:
    rate = get_settings().paper_taker_fee_rate
    notional = trade.size_usd * trade.leverage
    return round((notional + notional) * rate, 6)


def calculate_partial_close_pnl(trade: PaperTrade, exit_price: float, size_usd: float) -> dict[str, float]:
    raw_exit = exit_price or trade.exit_price or trade.entry_price
    price = _exit_price(trade.side, raw_exit)
    raw_pnl = _calculate_raw_pnl_for_size(trade, price, size_usd)
    fees = _fees_for_size(trade, size_usd)
    slippage_adjustment = _calculate_raw_pnl_for_size(trade, raw_exit, size_usd) - raw_pnl
    return {
        "exit_price": price,
        "raw_pnl": raw_pnl,
        "fees": fees,
        "slippage_adjustment": round(slippage_adjustment, 6),
        "net_pnl": round(raw_pnl - fees, 6),
    }


def unrealized_pnl_for_price(trade: PaperTrade, mark_price: float) -> dict[str, float]:
    if mark_price <= 0:
        return {"unrealized_pnl": trade.unrealized_pnl or 0, "unrealized_pnl_pct": trade.unrealized_pnl_pct or 0}
    pnl = _calculate_pnl(trade, mark_price)
    denominator = trade.size_usd * max(trade.leverage or 1, 1)
    pct = round(pnl / denominator * 100, 6) if denominator else 0
    return {"unrealized_pnl": pnl, "unrealized_pnl_pct": pct}


def _fees_for_size(trade: PaperTrade, size_usd: float) -> float:
    rate = get_settings().paper_taker_fee_rate
    notional = size_usd * trade.leverage
    return round((notional + notional) * rate, 6)


def _wallet_pnl(db: Session, closed: list[PaperTrade]) -> Dict[str, Optional[str]]:
    totals: Dict[int, float] = {}
    for trade in closed:
        totals[trade.wallet_id] = totals.get(trade.wallet_id, 0.0) + trade.pnl
    if not totals:
        return {"best": None, "worst": None}
    wallets = {wallet.id: wallet.name for wallet in db.query(Wallet).filter(Wallet.id.in_(totals.keys())).all()}
    best_id = max(totals, key=totals.get)
    worst_id = min(totals, key=totals.get)
    return {"best": wallets.get(best_id), "worst": wallets.get(worst_id)}


def _max_drawdown(closed: list[PaperTrade]) -> float:
    equity = STARTING_BALANCE
    peak = STARTING_BALANCE
    max_dd = 0.0
    for trade in sorted(closed, key=lambda item: item.closed_at or item.opened_at):
        equity += trade.pnl
        peak = max(peak, equity)
        if peak:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    return round(max_dd, 2)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
