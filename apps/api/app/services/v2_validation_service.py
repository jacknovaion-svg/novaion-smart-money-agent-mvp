import json
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.signal import PaperTrade, Signal
from app.models.v2_validation import DataQualityEvent, EquitySnapshot, PaperTradeAction, ShadowTrade, ShadowTradeAction


def record_equity_snapshot(db: Session, *, captured_at: Optional[datetime] = None) -> EquitySnapshot:
    settings = get_settings()
    shadow_trades = db.query(ShadowTrade).all()
    if settings.v2_alpha_validation_enabled and shadow_trades:
        realized = round(sum(trade.net_pnl or 0 for trade in shadow_trades if trade.status == "closed"), 6)
        unrealized = round(sum(trade.unrealized_pnl or 0 for trade in shadow_trades if trade.status == "open"), 6)
        source = "shadow_trading"
    else:
        closed = db.query(PaperTrade).filter(PaperTrade.status == "closed").all()
        opened = db.query(PaperTrade).filter(PaperTrade.status == "open").all()
        realized = round(sum(trade.net_pnl or trade.pnl or 0 for trade in closed), 6)
        unrealized = round(sum(trade.unrealized_pnl or 0 for trade in opened), 6)
        source = "paper_trading"
    starting = float(settings.paper_account_starting_balance_usd)
    snapshot = EquitySnapshot(
        captured_at=captured_at or datetime.now(timezone.utc),
        starting_balance=starting,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        net_pnl=round(realized + unrealized, 6),
        equity=round(starting + realized + unrealized, 6),
        source=source,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def equity_curve(db: Session) -> list[dict[str, Any]]:
    rows = db.query(EquitySnapshot).order_by(EquitySnapshot.captured_at.asc(), EquitySnapshot.id.asc()).all()
    return [
        {
            "captured_at": row.captured_at,
            "starting_balance": row.starting_balance,
            "realized_pnl": row.realized_pnl,
            "unrealized_pnl": row.unrealized_pnl,
            "net_pnl": row.net_pnl,
            "equity": row.equity,
            "source": row.source,
        }
        for row in rows
    ]


def max_drawdown(curve: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    if not curve:
        return {"amount": None, "percent": None}
    peak = float(curve[0]["equity"])
    worst_amount = 0.0
    worst_percent = 0.0
    for row in curve:
        equity = float(row["equity"])
        peak = max(peak, equity)
        amount = peak - equity
        percent = amount / peak * 100 if peak else 0.0
        worst_amount = max(worst_amount, amount)
        worst_percent = max(worst_percent, percent)
    return {"amount": round(worst_amount, 6), "percent": round(worst_percent, 6)}


def holding_time_stats(trades: list[PaperTrade]) -> dict[str, Any]:
    durations = [
        (_as_utc(trade.closed_at) - _as_utc(trade.opened_at)).total_seconds()
        for trade in trades
        if trade.status == "closed" and trade.closed_at and trade.opened_at
    ]
    return {
        "sample_count": len(durations),
        "average_seconds": round(sum(durations) / len(durations), 6) if durations else None,
        "median_seconds": round(median(durations), 6) if durations else None,
    }


def alpha_attribution(db: Session) -> dict[str, Any]:
    trades = db.query(PaperTrade).all()
    signals = {signal.id: signal for signal in db.query(Signal).all()}
    actions = db.query(PaperTradeAction).all()
    shadow_trades = db.query(ShadowTrade).all()
    shadow_actions = db.query(ShadowTradeAction).all()
    action_by_type = _action_metrics(actions, signals)
    return {
        "overall": _trade_metrics(trades),
        "wallets": _group_metrics(trades, lambda trade: trade.wallet_id),
        "symbols": _group_metrics(trades, lambda trade: trade.symbol),
        "signal_types": action_by_type or _group_metrics(
            [trade for trade in trades if trade.signal_id in signals],
            lambda trade: signals[trade.signal_id].signal_type,
        ),
        "shadow": {
            "overall": _shadow_metrics(shadow_trades),
            "wallets": _shadow_group_metrics(shadow_trades, lambda trade: trade.wallet_id),
            "symbols": _shadow_group_metrics(shadow_trades, lambda trade: trade.symbol),
            "actions": _shadow_action_metrics(shadow_actions),
        },
    }


def record_data_quality_event(
    db: Session,
    quality_type: str,
    *,
    signal: Optional[Signal] = None,
    wallet_id: Optional[int] = None,
    symbol: Optional[str] = None,
    severity: str = "warning",
    details: Optional[dict[str, Any]] = None,
) -> DataQualityEvent:
    event = DataQualityEvent(
        quality_type=quality_type,
        severity=severity,
        signal_id=signal.id if signal else None,
        wallet_id=wallet_id if wallet_id is not None else (signal.wallet_id if signal else None),
        symbol=symbol if symbol is not None else (signal.symbol if signal else None),
        details_json=json.dumps(details or {}, ensure_ascii=False, default=str),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def record_paper_trade_action(
    db: Session,
    *,
    signal: Signal,
    action_type: str,
    paper_trade: Optional[PaperTrade] = None,
    payload: Optional[dict[str, Any]] = None,
) -> PaperTradeAction:
    payload = payload or {}
    action = PaperTradeAction(
        signal_id=signal.id,
        paper_trade_id=paper_trade.id if paper_trade else None,
        wallet_id=signal.wallet_id,
        symbol=signal.symbol,
        action_type=action_type,
        gross_pnl=float(payload.get("gross_pnl", 0) or 0),
        fees=float(payload.get("fees", 0) or 0),
        slippage_adjustment=float(payload.get("slippage_adjustment", 0) or 0),
        net_pnl=float(payload.get("net_pnl", payload.get("realized_pnl", 0)) or 0),
        quality_status=str(payload.get("quality_status", "clean")),
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def create_shadow_trade(db: Session, signal: Signal) -> ShadowTrade:
    settings = get_settings()
    if settings.v3_enabled:
        raise ValueError("Legacy Shadow writes are disabled during V3")
    if not settings.v2_alpha_validation_enabled or not settings.shadow_trading_enabled:
        raise ValueError("Shadow Trading is disabled")
    if not settings.validation_mode:
        raise ValueError("Shadow Trading requires VALIDATION_MODE=true")
    if signal.signal_type not in {"open", "add"}:
        raise ValueError("Shadow Trading entry requires an open or add signal")
    if signal.current_price <= 0 and signal.source_entry_price <= 0:
        record_data_quality_event(db, "missing_mark_price", signal=signal, severity="error")
        raise ValueError("Signal has no usable price")
    existing = db.query(ShadowTrade).filter(ShadowTrade.signal_id == signal.id).first()
    if existing:
        return existing
    raw_price = signal.current_price or signal.source_entry_price
    side = "short" if signal.side == "short" else "long"
    slip = settings.paper_slippage_rate
    entry = raw_price * (1 - slip if side == "short" else 1 + slip)
    trade = ShadowTrade(
        signal_id=signal.id,
        wallet_id=signal.wallet_id,
        symbol=signal.symbol,
        side=side,
        size_usd=max(float(signal.suggested_size_usd or 0), 0),
        leverage=max(float(signal.source_leverage or 1), 1),
        entry_price=round(entry, 8),
        quality_status="clean",
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def process_new_signals_for_shadow(db: Session) -> dict[str, int]:
    """Process only post-cutover signals, one committed action at a time."""
    settings = get_settings()
    result = {"processed": 0, "ignored": 0, "failed": 0, "opened": 0, "added": 0, "reduced": 0, "closed": 0}
    if settings.v3_enabled:
        return result
    if not settings.v2_alpha_validation_enabled or not settings.shadow_trading_enabled or not settings.validation_mode:
        return result
    cutover = _parse_cutover(settings.paper_trading_cutover_at)
    if cutover is None:
        return result
    # SQLite may persist aware datetimes as differently formatted strings. Normalize
    # in Python so the cutover boundary is compared as an actual UTC instant.
    signals = [
        signal
        for signal in db.query(Signal).filter(Signal.status.in_(["new", "simulated"])).all()
        if signal.created_at and _as_utc(signal.created_at) >= cutover
    ]
    signals.sort(key=lambda signal: (_as_utc(signal.created_at), signal.id))
    for signal in signals:
        if db.query(ShadowTradeAction).filter(ShadowTradeAction.signal_id == signal.id).first():
            continue
        try:
            action = _process_shadow_signal(db, signal)
            result["processed"] += 1
            if action == "ignored":
                result["ignored"] += 1
            else:
                result[{"open": "opened", "add": "added", "reduce": "reduced", "close": "closed"}[action]] += 1
        except Exception:
            db.rollback()
            result["failed"] += 1
    return result


def update_shadow_positions(db: Session) -> int:
    """Mark open Shadow positions from the latest valid signal price."""
    updated = 0
    positions = db.query(ShadowTrade).filter(ShadowTrade.status == "open").all()
    for trade in positions:
        latest = (
            db.query(Signal)
            .filter(Signal.wallet_id == trade.wallet_id, Signal.symbol == trade.symbol, Signal.current_price > 0)
            .order_by(Signal.created_at.desc(), Signal.id.desc())
            .first()
        )
        if not latest:
            continue
        price = float(latest.current_price)
        direction = 1 if trade.side == "long" else -1
        trade.mark_price = price
        trade.unrealized_pnl = round(trade.size_usd * trade.leverage * ((price - trade.entry_price) / trade.entry_price) * direction, 6)
        updated += 1
    if updated:
        db.commit()
    return updated


def _process_shadow_signal(db: Session, signal: Signal) -> str:
    settings = get_settings()
    action_type = (signal.signal_type or "").lower()
    if action_type not in {"open", "add", "reduce", "close"}:
        return _ignore_shadow_signal(db, signal, "unsupported_signal_type")
    price = float(signal.current_price or signal.source_entry_price or 0)
    if not signal.symbol or price <= 0 or (signal.suggested_size_usd or 0) < 0:
        return _ignore_shadow_signal(db, signal, "missing_data")
    side = "short" if signal.side == "short" else "long"
    positions = db.query(ShadowTrade).filter(
        ShadowTrade.wallet_id == signal.wallet_id,
        ShadowTrade.symbol == signal.symbol,
        ShadowTrade.status == "open",
    ).order_by(ShadowTrade.id.asc()).all()
    if action_type == "close":
        if signal.side in {"long", "short"}:
            positions = [item for item in positions if item.side == signal.side]
        if len(positions) != 1:
            return _ignore_shadow_signal(db, signal, "ambiguous_close" if len(positions) > 1 else "orphan_close")
        trade = positions[0]
        gross, fees, slip, net, executed = _shadow_pnl(trade, trade.size_usd, price, close=True)
        trade.gross_pnl = round(trade.gross_pnl + gross, 6)
        trade.fees = round(trade.fees + fees, 6)
        trade.slippage_adjustment = round(trade.slippage_adjustment + slip, 6)
        trade.net_pnl = round(trade.net_pnl + net, 6)
        trade.exit_price = round(executed, 8)
        trade.size_usd = 0
        trade.status = "closed"
        trade.closed_at = datetime.now(timezone.utc)
        _add_shadow_action(db, signal, trade, "close", 0, trade.entry_price, executed, gross, fees, slip, net)
        signal.status = "simulated"
        db.commit()
        return "close"
    requested = float(signal.suggested_size_usd or 0)
    if requested <= 0:
        return _ignore_shadow_signal(db, signal, "zero_size")
    if action_type == "open":
        if positions:
            return _ignore_shadow_signal(db, signal, "duplicate_open")
        raw = price
        entry = raw * (1 - settings.paper_slippage_rate if side == "short" else 1 + settings.paper_slippage_rate)
        trade = ShadowTrade(signal_id=signal.id, wallet_id=signal.wallet_id, symbol=signal.symbol, side=side,
            size_usd=requested, leverage=max(float(signal.source_leverage or 1), 1), entry_price=round(entry, 8), quality_status="clean")
        db.add(trade)
        db.flush()
        _add_shadow_action(db, signal, trade, "open", requested, entry, 0, 0, 0, 0, 0)
        signal.status = "simulated"
        db.commit()
        return "open"
    if not positions:
        return _ignore_shadow_signal(db, signal, "orphan_" + action_type)
    trade = positions[0]
    if action_type == "add":
        old_qty = trade.size_usd * trade.leverage / trade.entry_price
        add_entry = price * (1 - settings.paper_slippage_rate if trade.side == "short" else 1 + settings.paper_slippage_rate)
        add_qty = requested * trade.leverage / add_entry
        trade.entry_price = round((old_qty * trade.entry_price + add_qty * add_entry) / (old_qty + add_qty), 8)
        trade.size_usd = round(trade.size_usd + requested, 6)
        _add_shadow_action(db, signal, trade, "add", requested, add_entry, 0, 0, 0, 0, 0)
        signal.status = "simulated"
        db.commit()
        return "add"
    reduce_size = round(trade.size_usd * 0.5, 6)
    gross, fees, slip, net, executed = _shadow_pnl(trade, reduce_size, price, close=True)
    trade.size_usd = round(trade.size_usd - reduce_size, 6)
    trade.gross_pnl = round(trade.gross_pnl + gross, 6)
    trade.fees = round(trade.fees + fees, 6)
    trade.slippage_adjustment = round(trade.slippage_adjustment + slip, 6)
    trade.net_pnl = round(trade.net_pnl + net, 6)
    _add_shadow_action(db, signal, trade, "reduce", reduce_size, trade.entry_price, executed, gross, fees, slip, net)
    signal.status = "simulated"
    db.commit()
    return "reduce"


def _ignore_shadow_signal(db: Session, signal: Signal, reason: str) -> str:
    trade = db.query(ShadowTrade).filter(ShadowTrade.wallet_id == signal.wallet_id, ShadowTrade.symbol == signal.symbol, ShadowTrade.status == "open").first()
    _add_shadow_action(db, signal, trade, signal.signal_type or "unknown", 0, 0, 0, 0, 0, 0, 0, status="ignored", reason=reason)
    if signal.status == "new":
        signal.status = "ignored"
    db.commit()
    return "ignored"


def _add_shadow_action(db: Session, signal: Signal, trade: Optional[ShadowTrade], action_type: str, size: float, entry: float, exit_price: float,
                       gross: float, fees: float, slip: float, net: float, *, status: str = "processed", reason: str = "") -> ShadowTradeAction:
    action = ShadowTradeAction(signal_id=signal.id, shadow_trade_id=trade.id if trade else None, wallet_id=signal.wallet_id,
        symbol=signal.symbol, side=trade.side if trade else (signal.side or "long"), action_type=action_type, size_usd=size,
        entry_price=entry, exit_price=exit_price, gross_pnl=gross, fees=fees, slippage_adjustment=slip, net_pnl=net, status=status, reason=reason)
    db.add(action)
    return action


def _shadow_pnl(trade: ShadowTrade, size: float, price: float, *, close: bool) -> tuple[float, float, float, float, float]:
    settings = get_settings()
    executed = price * (1 + settings.paper_slippage_rate if trade.side == "short" else 1 - settings.paper_slippage_rate)
    direction = 1 if trade.side == "long" else -1
    notional = size * trade.leverage
    gross = notional * ((executed - trade.entry_price) / trade.entry_price) * direction
    fees = (notional + notional) * settings.paper_taker_fee_rate
    slip = notional * ((price - trade.entry_price) / trade.entry_price) * direction - gross
    return round(gross, 6), round(fees, 6), round(slip, 6), round(gross - fees, 6), round(executed, 8)


def _parse_cutover(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _as_utc(parsed)
    except ValueError:
        return None


def close_shadow_trade(db: Session, trade: ShadowTrade, exit_price: float) -> ShadowTrade:
    if trade.status != "open":
        return trade
    if exit_price <= 0:
        raise ValueError("Exit price must be positive")
    settings = get_settings()
    slip = settings.paper_slippage_rate
    executed = exit_price * (1 + slip if trade.side == "short" else 1 - slip)
    direction = 1 if trade.side == "long" else -1
    gross = trade.size_usd * trade.leverage * ((executed - trade.entry_price) / trade.entry_price) * direction
    notional = trade.size_usd * trade.leverage
    fees = (notional + notional) * settings.paper_taker_fee_rate
    trade.exit_price = round(executed, 8)
    trade.gross_pnl = round(gross, 6)
    trade.fees = round(fees, 6)
    trade.slippage_adjustment = round(
        trade.size_usd * trade.leverage * ((exit_price - trade.entry_price) / trade.entry_price) * direction - gross,
        6,
    )
    trade.net_pnl = round(gross - fees, 6)
    trade.status = "closed"
    trade.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trade)
    return trade


def shadow_summary(db: Session) -> dict[str, Any]:
    trades = db.query(ShadowTrade).all()
    closed = [trade for trade in trades if trade.status == "closed"]
    wins = [trade for trade in closed if trade.net_pnl > 0]
    gross_profit = sum(trade.net_pnl for trade in wins)
    gross_loss = sum(-trade.net_pnl for trade in closed if trade.net_pnl < 0)
    return {
        "trades": len(trades),
        "open_trades": sum(trade.status == "open" for trade in trades),
        "closed_trades": len(closed),
        "win_rate": round(len(wins) / len(closed) * 100, 6) if closed else None,
        "gross_pnl": round(sum(trade.gross_pnl for trade in closed), 6),
        "net_pnl": round(sum(trade.net_pnl for trade in closed), 6),
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "expectancy": round(sum(trade.net_pnl for trade in closed) / len(closed), 6) if closed else None,
        "holding_time": holding_time_stats(closed),
    }


def _trade_metrics(trades: list[PaperTrade]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.status == "closed"]
    winners = [trade for trade in closed if (trade.net_pnl or trade.pnl or 0) > 0]
    losers = [trade for trade in closed if (trade.net_pnl or trade.pnl or 0) < 0]
    gross = sum(trade.raw_pnl or 0 for trade in closed)
    net = sum(trade.net_pnl or trade.pnl or 0 for trade in closed)
    gross_profit = sum(trade.net_pnl or trade.pnl or 0 for trade in winners)
    gross_loss = sum(-(trade.net_pnl or trade.pnl or 0) for trade in losers)
    return {
        "signals": len({trade.signal_id for trade in trades}),
        "trades": len(trades),
        "closed_trades": len(closed),
        "win_rate": round(len(winners) / len(closed) * 100, 6) if closed else None,
        "gross_pnl": round(gross, 6),
        "net_pnl": round(net, 6),
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "expectancy": round(net / len(closed), 6) if closed else None,
        "average_trade": round(net / len(closed), 6) if closed else None,
        "holding_time": holding_time_stats(closed),
    }


def _group_metrics(trades: list[PaperTrade], key_fn) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for trade in trades:
        groups[str(key_fn(trade))].append(trade)
    return [{"key": key, **_trade_metrics(group)} for key, group in sorted(groups.items())]


def _shadow_metrics(trades: list[ShadowTrade]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.status == "closed"]
    winners = [trade for trade in closed if trade.net_pnl > 0]
    losers = [trade for trade in closed if trade.net_pnl < 0]
    gross_profit = sum(trade.net_pnl for trade in winners)
    gross_loss = sum(-trade.net_pnl for trade in losers)
    return {
        "trades": len(trades),
        "closed_trades": len(closed),
        "win_rate": round(len(winners) / len(closed) * 100, 6) if closed else None,
        "gross_pnl": round(sum(trade.gross_pnl for trade in closed), 6),
        "net_pnl": round(sum(trade.net_pnl for trade in closed), 6),
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "expectancy": round(sum(trade.net_pnl for trade in closed) / len(closed), 6) if closed else None,
    }


def _shadow_group_metrics(trades: list[ShadowTrade], key_fn) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for trade in trades:
        groups[str(key_fn(trade))].append(trade)
    return [{"key": key, **_shadow_metrics(group)} for key, group in sorted(groups.items())]


def _shadow_action_metrics(actions: list[ShadowTradeAction]) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for action in actions:
        groups[action.action_type].append(action)
    return [{"key": key, "signals": len(group), "net_pnl": round(sum(item.net_pnl for item in group), 6)} for key, group in sorted(groups.items())]


def _action_metrics(actions: list[PaperTradeAction], signals: dict[int, Signal]) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for action in actions:
        groups[action.action_type].append(action)
    rows = []
    for key, group in sorted(groups.items()):
        closed = [item for item in group if item.action_type in {"paper_reduced", "paper_closed"}]
        winners = [item for item in closed if item.net_pnl > 0]
        losses = [item for item in closed if item.net_pnl < 0]
        gross_profit = sum(item.net_pnl for item in winners)
        gross_loss = sum(-item.net_pnl for item in losses)
        rows.append(
            {
                "key": key,
                "signals": len({item.signal_id for item in group}),
                "trades": len({item.paper_trade_id for item in group if item.paper_trade_id}),
                "closed_trades": len(closed),
                "win_rate": round(len(winners) / len(closed) * 100, 6) if closed else None,
                "gross_pnl": round(sum(item.gross_pnl for item in closed), 6),
                "net_pnl": round(sum(item.net_pnl for item in closed), 6),
                "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
                "expectancy": round(sum(item.net_pnl for item in closed) / len(closed), 6) if closed else None,
                "average_trade": round(sum(item.net_pnl for item in closed) / len(closed), 6) if closed else None,
            }
        )
    return rows


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
