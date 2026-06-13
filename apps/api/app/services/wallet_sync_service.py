import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.market_data import (
    SyncState,
    WalletFill,
    WalletOrderSnapshot,
    WalletPositionSnapshot,
)
from app.models.wallet import Wallet
from app.services.hyperliquid_client import HyperliquidApiClient
from app.services.metrics_service import calculate_wallet_metrics
from app.services.signal_service import generate_signals_for_wallet
from app.services.system_log_service import write_log


def sync_enabled_hyperliquid_wallets(db: Session) -> dict[str, Any]:
    wallets = (
        db.query(Wallet)
        .filter(Wallet.status == "active", Wallet.platform == "hyperliquid")
        .order_by(Wallet.created_at.asc())
        .all()
    )
    result = {"synced_wallets": 0, "fills_inserted": 0, "errors": []}
    for wallet in wallets:
        try:
            wallet_result = sync_wallet_market_data(db, wallet)
            result["synced_wallets"] += 1
            result["fills_inserted"] += wallet_result["fills_inserted"]
        except Exception as exc:
            message = f"{wallet.name}: {exc}"
            result["errors"].append(message)
            write_log(
                db,
                level="error",
                module="wallet_sync",
                message="Wallet sync failed",
                payload={"wallet_id": wallet.id, "error": str(exc)},
            )
    return result


def sync_wallet_market_data(db: Session, wallet: Wallet) -> dict[str, Any]:
    client = HyperliquidApiClient(db)
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    mids = client.get_all_mids()

    state = _get_sync_state(db, wallet.id, "hyperliquid_fills")
    start_ms = _next_start_ms(state)

    fills = client.get_user_fills_by_time(wallet.address, start_ms, now_ms)
    fills_inserted = _store_fills(db, wallet.id, fills)
    if fills:
        max_time = max(int(fill.get("time", start_ms)) for fill in fills)
        state.cursor_value = str(max_time + 1)
    elif not state.cursor_value:
        state.cursor_value = str(now_ms - 60_000)
    state.status = "ok"
    state.error_message = ""
    state.updated_at = now
    db.commit()

    clearinghouse_state = client.get_clearinghouse_state(wallet.address)
    _store_position_snapshot(db, wallet.id, clearinghouse_state)

    open_orders = client.get_open_orders(wallet.address)
    _store_order_snapshot(db, wallet.id, open_orders)

    calculate_wallet_metrics(db, wallet)
    signals = generate_signals_for_wallet(db, wallet, mids)
    write_log(
        db,
        level="info",
        module="wallet_sync",
        message="Wallet market data synced",
        payload={"wallet_id": wallet.id, "fills_inserted": fills_inserted, "signals": len(signals)},
    )
    return {"fills_inserted": fills_inserted}


def recalculate_enabled_wallet_metrics(db: Session) -> int:
    wallets = db.query(Wallet).filter(Wallet.status == "active").all()
    for wallet in wallets:
        calculate_wallet_metrics(db, wallet)
    write_log(
        db,
        level="info",
        module="metrics",
        message="Wallet metrics recalculated",
        payload={"wallets": len(wallets)},
    )
    return len(wallets)


def _get_sync_state(db: Session, wallet_id: int, sync_type: str) -> SyncState:
    state = (
        db.query(SyncState)
        .filter(SyncState.wallet_id == wallet_id, SyncState.sync_type == sync_type)
        .first()
    )
    if state:
        return state
    state = SyncState(wallet_id=wallet_id, sync_type=sync_type, status="idle")
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def _next_start_ms(state: SyncState) -> int:
    settings = get_settings()
    if state.cursor_value:
        return int(state.cursor_value)
    start = datetime.now(timezone.utc) - timedelta(days=settings.hyperliquid_initial_lookback_days)
    return int(start.timestamp() * 1000)


def _store_fills(db: Session, wallet_id: int, fills: list[Dict[str, Any]]) -> int:
    inserted = 0
    for fill in fills:
        source_trade_id = _fill_source_id(fill)
        trade_time = datetime.fromtimestamp(int(fill.get("time", 0)) / 1000, tz=timezone.utc)
        wallet_fill = WalletFill(
            wallet_id=wallet_id,
            source_trade_id=source_trade_id,
            coin=str(fill.get("coin", "")),
            side=str(fill.get("side", "")),
            price=_to_float(fill.get("px")),
            size=_to_float(fill.get("sz")),
            closed_pnl=_to_float(fill.get("closedPnl")),
            fee=_to_float(fill.get("fee")),
            raw_json=json.dumps(fill, ensure_ascii=False),
            trade_time=trade_time,
        )
        db.add(wallet_fill)
        try:
            db.commit()
            inserted += 1
        except IntegrityError:
            db.rollback()
    return inserted


def _store_position_snapshot(db: Session, wallet_id: int, raw_state: Dict[str, Any]) -> None:
    positions = []
    total_unrealized = 0.0
    for item in raw_state.get("assetPositions", []):
        position = item.get("position", {})
        size = _to_float(position.get("szi"))
        if size == 0:
            continue
        unrealized = _to_float(position.get("unrealizedPnl"))
        total_unrealized += unrealized
        positions.append(
            {
                "coin": position.get("coin", ""),
                "side": "long" if size > 0 else "short",
                "size": abs(size),
                "signed_size": size,
                "entry_price": _to_float(position.get("entryPx")),
                "position_value": _to_float(position.get("positionValue")),
                "unrealized_pnl": unrealized,
                "leverage": _parse_leverage(position.get("leverage")),
            }
        )
    snapshot = WalletPositionSnapshot(
        wallet_id=wallet_id,
        raw_json=json.dumps(raw_state, ensure_ascii=False),
        positions_json=json.dumps(positions, ensure_ascii=False),
        account_value=_to_float(raw_state.get("marginSummary", {}).get("accountValue")),
        unrealized_pnl=total_unrealized,
    )
    db.add(snapshot)
    db.commit()


def _store_order_snapshot(db: Session, wallet_id: int, raw_orders: list[Dict[str, Any]]) -> None:
    snapshot = WalletOrderSnapshot(
        wallet_id=wallet_id,
        raw_json=json.dumps(raw_orders, ensure_ascii=False),
        open_order_count=len(raw_orders),
    )
    db.add(snapshot)
    db.commit()


def _fill_source_id(fill: Dict[str, Any]) -> str:
    for key in ("tid", "hash", "oid", "cloid"):
        if fill.get(key) is not None:
            return f"{key}:{fill[key]}"
    payload = json.dumps(fill, sort_keys=True, ensure_ascii=False)
    return "hash:" + hashlib.sha256(payload.encode()).hexdigest()


def _parse_leverage(raw: Any) -> float:
    if isinstance(raw, dict):
        return _to_float(raw.get("value"))
    return _to_float(raw)


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
