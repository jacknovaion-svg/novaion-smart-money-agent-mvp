import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.signal import PaperTrade, Signal
from app.services.hyperliquid_client import HyperliquidApiClient
from app.services.paper_trading_service import (
    _entry_price,
    _paper_leverage,
    _stop_loss,
    _take_profit,
    add_signal_to_paper,
    calculate_partial_close_pnl,
    close_paper_trade,
    unrealized_pnl_for_price,
)
from app.services.system_log_service import write_log


SIMULATION_RULE_VERSION = "paper_v1"
PAPER_ACTIONS = {
    "paper_opened",
    "paper_added",
    "paper_reduced",
    "paper_closed",
    "duplicate_open",
    "orphan_add",
    "orphan_reduce",
    "orphan_close",
    "ambiguous_close",
    "high_risk",
    "zero_size",
    "missing_data",
}


def get_or_create_paper_trading_cutover(db: Session) -> datetime:
    settings = get_settings()
    if settings.paper_trading_cutover_at:
        return _parse_utc(settings.paper_trading_cutover_at)

    path = _cutover_path()
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _parse_utc(payload["paper_trading_cutover_at"])

    cutover_at = datetime.now(timezone.utc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"paper_trading_cutover_at": cutover_at.isoformat()}, indent=2),
        encoding="utf-8",
    )
    write_log(
        db,
        level="info",
        module="paper_trading",
        message="Paper trading cutover set",
        payload={"paper_trading_cutover_at": cutover_at.isoformat()},
    )
    return cutover_at


def process_new_signals_for_paper_trading(
    db: Session,
    *,
    cutover_at: Optional[datetime] = None,
    limit: int = 200,
) -> dict[str, Any]:
    cutover = cutover_at or get_or_create_paper_trading_cutover(db)
    signals = (
        db.query(Signal)
        .filter(Signal.status == "new", Signal.created_at >= cutover)
        .order_by(Signal.created_at.asc(), Signal.id.asc())
        .limit(limit)
        .all()
    )
    result: dict[str, Any] = {
        "cutover_at": cutover.isoformat(),
        "processed": 0,
        "simulated": 0,
        "ignored": 0,
        "failed": 0,
        "paper_opened": 0,
        "paper_added": 0,
        "paper_reduced": 0,
        "paper_closed": 0,
    }
    for signal in signals:
        outcome = process_signal_for_paper_trading(db, signal)
        result["processed"] += 1
        result[outcome["status"]] = result.get(outcome["status"], 0) + 1
        action = outcome.get("action")
        if action in result:
            result[action] += 1
    return result


def process_signal_for_paper_trading(db: Session, signal: Signal) -> dict[str, Any]:
    try:
        existing_action = _paper_action_exists(db, signal.id)
        if existing_action:
            return _ignore_signal(db, signal, "duplicate_processed", {"existing_action": existing_action})

        validation_error = _validate_signal(signal)
        if validation_error:
            return _ignore_signal(db, signal, validation_error)

        signal_type = (signal.signal_type or "").lower()
        if signal_type == "open":
            return _process_open(db, signal)
        if signal_type == "add":
            return _process_add(db, signal)
        if signal_type == "reduce":
            return _process_reduce(db, signal)
        if signal_type == "close":
            return _process_close(db, signal)
        return _ignore_signal(db, signal, "unsupported_signal_type")
    except Exception as exc:
        db.rollback()
        signal.status = "failed"
        db.add(signal)
        db.commit()
        _log_action(db, signal, "error_message", {"error_message": str(exc)}, level="error")
        return {"status": "failed", "action": "error_message"}


def update_open_paper_trades(db: Session, mids: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    trades = db.query(PaperTrade).filter(PaperTrade.status == "open").all()
    result = {"open_trades": len(trades), "updated": 0, "price_missing": 0, "failed": 0}
    if not trades:
        return result

    prices = mids
    if prices is None:
        try:
            prices = HyperliquidApiClient(db).get_all_mids()
        except Exception as exc:
            write_log(
                db,
                level="error",
                module="paper_trading",
                message="Paper mark price refresh failed",
                payload={"action": "missing_data", "error_message": str(exc), "timestamp": _now_iso()},
            )
            return {**result, "failed": len(trades)}

    for trade in trades:
        try:
            raw_price = _price_for_symbol(prices or {}, trade.symbol)
            if raw_price is None or raw_price <= 0:
                result["price_missing"] += 1
                _log_trade_event(db, trade, "missing_data", {"reason": "mark_price_missing"})
                continue
            pnl = unrealized_pnl_for_price(trade, raw_price)
            trade.mark_price = raw_price
            trade.unrealized_pnl = pnl["unrealized_pnl"]
            trade.unrealized_pnl_pct = pnl["unrealized_pnl_pct"]
            trade.updated_at = datetime.now(timezone.utc)
            result["updated"] += 1
        except Exception as exc:
            result["failed"] += 1
            _log_trade_event(db, trade, "error_message", {"error_message": str(exc)}, level="error")
    db.commit()
    return result


def generate_historical_dry_run_report(
    db: Session,
    *,
    cutover_at: Optional[datetime] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    cutover = cutover_at or get_or_create_paper_trading_cutover(db)
    signals = (
        db.query(Signal)
        .filter(Signal.status == "new", Signal.created_at < cutover)
        .order_by(Signal.created_at.asc(), Signal.id.asc())
        .all()
    )
    counts: dict[str, Any] = {
        "cutover_at": cutover.isoformat(),
        "historical_new_signals": len(signals),
        "processable": 0,
        "open": 0,
        "add": 0,
        "reduce": 0,
        "close": 0,
        "high_risk": 0,
        "zero_size": 0,
        "missing_data": 0,
        "duplicate_open": 0,
        "orphan_add": 0,
        "orphan_reduce": 0,
        "orphan_close": 0,
        "ambiguous_close": 0,
    }
    open_positions: set[tuple[int, str, str]] = set()
    for signal in signals:
        reason = _validate_signal(signal)
        if reason in {"high_risk", "zero_size", "missing_data"}:
            counts[reason] += 1
            continue
        signal_type = (signal.signal_type or "").lower()
        if signal_type in counts:
            counts[signal_type] += 1
        side = _position_side(signal)
        key = (signal.wallet_id, signal.symbol, side or "")
        if signal_type == "open":
            if not side:
                counts["missing_data"] += 1
            elif key in open_positions:
                counts["duplicate_open"] += 1
            else:
                open_positions.add(key)
                counts["processable"] += 1
        elif signal_type == "add":
            if not side or key not in open_positions:
                counts["orphan_add"] += 1
            else:
                counts["processable"] += 1
        elif signal_type == "reduce":
            if not side or key not in open_positions:
                counts["orphan_reduce"] += 1
            else:
                counts["processable"] += 1
        elif signal_type == "close":
            matches = [item for item in open_positions if item[0] == signal.wallet_id and item[1] == signal.symbol]
            if side:
                matches = [item for item in matches if item[2] == side]
            if not matches:
                counts["orphan_close"] += 1
            elif len(matches) > 1:
                counts["ambiguous_close"] += 1
            else:
                open_positions.remove(matches[0])
                counts["processable"] += 1

    path = Path(output_path) if output_path else Path.cwd() / "Paper_Trading_Historical_Dry_Run_Report.md"
    path.write_text(_dry_run_markdown(counts), encoding="utf-8")
    counts["report_path"] = str(path)
    return counts


def _process_open(db: Session, signal: Signal) -> dict[str, Any]:
    side = _position_side(signal)
    if not side:
        return _ignore_signal(db, signal, "missing_data")
    existing = _open_trade(db, signal.wallet_id, signal.symbol, side)
    if existing:
        return _ignore_signal(db, signal, "duplicate_open", paper_trade_id=existing.id)
    trade = add_signal_to_paper(db, signal)
    _log_action(db, signal, "paper_opened", {"paper_trade_id": trade.id}, paper_trade_id=trade.id)
    return {"status": "simulated", "action": "paper_opened", "paper_trade_id": trade.id}


def _process_add(db: Session, signal: Signal) -> dict[str, Any]:
    side = _position_side(signal)
    if not side:
        return _ignore_signal(db, signal, "missing_data")
    trade = _open_trade(db, signal.wallet_id, signal.symbol, side)
    if not trade:
        return _ignore_signal(db, signal, "orphan_add")

    settings = get_settings()
    capacity = max(settings.paper_max_position_usd - (trade.size_usd or 0), 0)
    add_size = min(signal.suggested_size_usd or 0, capacity)
    if add_size <= 0:
        return _ignore_signal(db, signal, "zero_size", {"reason": "max_position_reached"}, paper_trade_id=trade.id)

    raw_price = _signal_price(signal)
    entry_price = _entry_price(side, raw_price)
    old_size = trade.size_usd or 0
    new_size = old_size + add_size
    trade.entry_price = round(((trade.entry_price * old_size) + (entry_price * add_size)) / new_size, 8)
    trade.size_usd = round(new_size, 6)
    trade.leverage = round(((trade.leverage * old_size) + (_paper_leverage(signal.source_leverage) * add_size)) / new_size, 6)
    trade.mark_price = raw_price
    pnl = unrealized_pnl_for_price(trade, raw_price)
    trade.unrealized_pnl = pnl["unrealized_pnl"]
    trade.unrealized_pnl_pct = pnl["unrealized_pnl_pct"]
    trade.updated_at = datetime.now(timezone.utc)
    signal.status = "simulated"
    db.commit()
    _log_action(
        db,
        signal,
        "paper_added",
        {"paper_trade_id": trade.id, "added_size_usd": add_size, "new_size_usd": trade.size_usd},
        paper_trade_id=trade.id,
    )
    return {"status": "simulated", "action": "paper_added", "paper_trade_id": trade.id}


def _process_reduce(db: Session, signal: Signal) -> dict[str, Any]:
    side = _position_side(signal)
    if not side:
        return _ignore_signal(db, signal, "missing_data")
    trade = _open_trade(db, signal.wallet_id, signal.symbol, side)
    if not trade:
        return _ignore_signal(db, signal, "orphan_reduce")

    raw_price = _signal_price(signal)
    reduce_size = round((trade.size_usd or 0) * 0.5, 6)
    if reduce_size <= 0:
        return _ignore_signal(db, signal, "zero_size", paper_trade_id=trade.id)
    realized = calculate_partial_close_pnl(trade, raw_price, reduce_size)
    trade.size_usd = round((trade.size_usd or 0) - reduce_size, 6)
    trade.exit_price = realized["exit_price"]
    trade.raw_pnl = round((trade.raw_pnl or 0) + realized["raw_pnl"], 6)
    trade.fees = round((trade.fees or 0) + realized["fees"], 6)
    trade.slippage_adjustment = round((trade.slippage_adjustment or 0) + realized["slippage_adjustment"], 6)
    trade.net_pnl = round((trade.net_pnl or 0) + realized["net_pnl"], 6)
    trade.pnl = trade.net_pnl
    trade.mark_price = raw_price
    pnl = unrealized_pnl_for_price(trade, raw_price)
    trade.unrealized_pnl = pnl["unrealized_pnl"]
    trade.unrealized_pnl_pct = pnl["unrealized_pnl_pct"]
    trade.updated_at = datetime.now(timezone.utc)
    signal.status = "simulated"
    db.commit()
    _log_action(
        db,
        signal,
        "paper_reduced",
        {
            "paper_trade_id": trade.id,
            "reduced_size_usd": reduce_size,
            "remaining_size_usd": trade.size_usd,
            "realized_pnl": realized["net_pnl"],
            "simulation_rule_version": SIMULATION_RULE_VERSION,
            "reduce_rule": "fixed_50_percent",
        },
        paper_trade_id=trade.id,
    )
    return {"status": "simulated", "action": "paper_reduced", "paper_trade_id": trade.id}


def _process_close(db: Session, signal: Signal) -> dict[str, Any]:
    side = _position_side(signal)
    query = db.query(PaperTrade).filter(
        PaperTrade.wallet_id == signal.wallet_id,
        PaperTrade.symbol == signal.symbol,
        PaperTrade.status == "open",
    )
    if side:
        query = query.filter(PaperTrade.side == side)
    trades = query.all()
    if not trades:
        return _ignore_signal(db, signal, "orphan_close")
    if len(trades) > 1:
        return _ignore_signal(db, signal, "ambiguous_close")

    trade = close_paper_trade(db, trades[0], _signal_price(signal))
    signal.status = "simulated"
    db.commit()
    _log_action(db, signal, "paper_closed", {"paper_trade_id": trade.id, "realized_pnl": trade.pnl}, paper_trade_id=trade.id)
    return {"status": "simulated", "action": "paper_closed", "paper_trade_id": trade.id}


def _ignore_signal(
    db: Session,
    signal: Signal,
    action: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    paper_trade_id: Optional[int] = None,
) -> dict[str, Any]:
    signal.status = "ignored"
    db.commit()
    _log_action(db, signal, action, payload or {}, paper_trade_id=paper_trade_id)
    return {"status": "ignored", "action": action, "paper_trade_id": paper_trade_id}


def _log_action(
    db: Session,
    signal: Signal,
    action: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    paper_trade_id: Optional[int] = None,
    level: str = "info",
) -> None:
    body = {
        "signal_id": signal.id,
        "wallet_id": signal.wallet_id,
        "symbol": signal.symbol,
        "action": action,
        "timestamp": _now_iso(),
        "paper_trade_id": paper_trade_id,
    }
    body.update(payload or {})
    write_log(db, level=level, module="paper_trading", message=action, payload=body)


def _log_trade_event(
    db: Session,
    trade: PaperTrade,
    action: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    level: str = "info",
) -> None:
    body = {
        "signal_id": trade.signal_id,
        "wallet_id": trade.wallet_id,
        "symbol": trade.symbol,
        "action": action,
        "timestamp": _now_iso(),
        "paper_trade_id": trade.id,
    }
    body.update(payload or {})
    write_log(db, level=level, module="paper_trading", message=action, payload=body)


def _paper_action_exists(db: Session, signal_id: int) -> Optional[str]:
    from app.models.system_log import SystemLog

    logs = (
        db.query(SystemLog)
        .filter(SystemLog.module == "paper_trading")
        .order_by(SystemLog.created_at.desc())
        .limit(1000)
        .all()
    )
    for log in logs:
        try:
            payload = json.loads(log.payload_json or "{}")
        except json.JSONDecodeError:
            continue
        if payload.get("signal_id") != signal_id:
            continue
        action = payload.get("action")
        if action in PAPER_ACTIONS or action == "error_message":
            return action
    return None


def _validate_signal(signal: Signal) -> Optional[str]:
    if not signal.symbol or not signal.signal_type:
        return "missing_data"
    if (signal.risk_score or 0) > 80:
        return "high_risk"
    if (signal.suggested_size_usd or 0) <= 0 and (signal.signal_type or "").lower() != "close":
        return "zero_size"
    if _signal_price(signal) <= 0:
        return "missing_data"
    if (signal.signal_type or "").lower() in {"open", "add", "reduce"} and not _position_side(signal):
        return "missing_data"
    return None


def _open_trade(db: Session, wallet_id: int, symbol: str, side: str) -> Optional[PaperTrade]:
    return (
        db.query(PaperTrade)
        .filter(
            PaperTrade.wallet_id == wallet_id,
            PaperTrade.symbol == symbol,
            PaperTrade.side == side,
            PaperTrade.status == "open",
        )
        .first()
    )


def _position_side(signal: Signal) -> Optional[str]:
    side = (signal.side or "").lower()
    return side if side in {"long", "short"} else None


def _signal_price(signal: Signal) -> float:
    return float(signal.current_price or signal.source_entry_price or 0)


def _price_for_symbol(prices: dict[str, Any], symbol: str) -> Optional[float]:
    candidates = [symbol, symbol.upper(), symbol.split("-")[0], symbol.split("/")[0]]
    for key in candidates:
        if key in prices:
            try:
                return float(prices[key])
            except (TypeError, ValueError):
                return None
    return None


def _cutover_path() -> Path:
    settings = get_settings()
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        return db_path.parent / "paper_trading_cutover.json"
    return Path.cwd() / "data" / "paper_trading_cutover.json"


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dry_run_markdown(counts: dict[str, Any]) -> str:
    lines = [
        "# Paper Trading Historical Dry Run Report",
        "",
        f"- cutover_at: {counts['cutover_at']}",
        f"- historical_new_signals: {counts['historical_new_signals']}",
        f"- processable: {counts['processable']}",
        f"- open: {counts['open']}",
        f"- add: {counts['add']}",
        f"- reduce: {counts['reduce']}",
        f"- close: {counts['close']}",
        f"- high_risk: {counts['high_risk']}",
        f"- zero_size: {counts['zero_size']}",
        f"- missing_data: {counts['missing_data']}",
        f"- duplicate_open: {counts['duplicate_open']}",
        f"- orphan_add: {counts['orphan_add']}",
        f"- orphan_reduce: {counts['orphan_reduce']}",
        f"- orphan_close: {counts['orphan_close']}",
        f"- ambiguous_close: {counts['ambiguous_close']}",
        "",
        "No paper trades were created and no historical signal status was changed.",
    ]
    return "\n".join(lines) + "\n"
