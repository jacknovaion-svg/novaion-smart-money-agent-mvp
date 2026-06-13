import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.market_data import WalletMetric, WalletPositionSnapshot
from app.models.signal import RiskRule, Signal
from app.models.wallet import Wallet
from app.services.system_log_service import write_log
from app.services.telegram_service import send_signal_notification


def generate_signals_for_wallet(db: Session, wallet: Wallet, current_prices: Optional[Dict[str, str]] = None) -> List[Signal]:
    snapshots = (
        db.query(WalletPositionSnapshot)
        .filter(WalletPositionSnapshot.wallet_id == wallet.id)
        .order_by(WalletPositionSnapshot.created_at.desc())
        .limit(2)
        .all()
    )
    if not snapshots:
        return []

    current_snapshot = snapshots[0]
    previous_positions = _positions_by_coin(snapshots[1]) if len(snapshots) > 1 else {}
    current_positions = _positions_by_coin(current_snapshot)
    metric = db.query(WalletMetric).filter(WalletMetric.wallet_id == wallet.id).first()
    risk_rule = db.query(RiskRule).order_by(RiskRule.id.asc()).first()
    current_prices = current_prices or {}
    created_signals = []

    for coin, current in current_positions.items():
        previous = previous_positions.get(coin)
        signal_type = None
        if previous is None:
            signal_type = "open"
        elif current["side"] != previous["side"]:
            signal_type = "open"
        elif current["size"] > previous["size"]:
            signal_type = "add"
        elif current["size"] < previous["size"]:
            signal_type = "reduce"

        if signal_type:
            signal = _create_signal(db, wallet, metric, risk_rule, current_snapshot, current, signal_type, current_prices)
            if signal:
                created_signals.append(signal)

    for coin, previous in previous_positions.items():
        if coin not in current_positions:
            closed_position = dict(previous)
            closed_position["size"] = 0
            signal = _create_signal(db, wallet, metric, risk_rule, current_snapshot, closed_position, "close", current_prices)
            if signal:
                created_signals.append(signal)

    if created_signals:
        write_log(
            db,
            level="info",
            module="signals",
            message="Signals generated",
            payload={"wallet_id": wallet.id, "count": len(created_signals)},
        )
    return created_signals


def _create_signal(
    db: Session,
    wallet: Wallet,
    metric: Optional[WalletMetric],
    risk_rule: Optional[RiskRule],
    snapshot: WalletPositionSnapshot,
    position: Dict[str, Any],
    signal_type: str,
    current_prices: Dict[str, str],
) -> Optional[Signal]:
    symbol = str(position.get("coin", ""))
    side = "close" if signal_type == "close" else str(position.get("side", "long"))
    current_price = _to_float(current_prices.get(symbol)) or _to_float(position.get("entry_price"))
    source_value = _to_float(position.get("position_value"))
    leverage = _to_float(position.get("leverage"))
    risk_block = _risk_rule_block_reason(wallet, metric, risk_rule, position)
    if risk_block:
        write_log(
            db,
            level="info",
            module="signals",
            message="Signal skipped by risk rules",
            payload={"wallet_id": wallet.id, "symbol": symbol, "reason": risk_block},
        )
        return None
    dedupe_key = _dedupe_key(wallet.id, snapshot.id, symbol, signal_type, position)
    confidence_score = _confidence_score(wallet, metric)
    risk_score = _risk_score(position, metric)
    suggested_size = 0 if risk_score > 80 else 20
    reason = _reason(wallet, metric, leverage, risk_score)
    signal = Signal(
        wallet_id=wallet.id,
        platform=wallet.platform,
        symbol=symbol,
        signal_type=signal_type,
        side=side,
        source_size=source_value,
        source_leverage=leverage,
        source_entry_price=_to_float(position.get("entry_price")),
        current_price=current_price,
        confidence_score=confidence_score,
        risk_score=risk_score,
        suggested_action="Only simulate. Do not live trade." if risk_score <= 80 else "Skip simulation due to high risk.",
        suggested_size_usd=suggested_size,
        reason=reason,
        status="new",
        source_trade_id=dedupe_key,
        dedupe_key=dedupe_key,
    )
    db.add(signal)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(signal)
    send_signal_notification(db, signal, wallet)
    return signal


def _positions_by_coin(snapshot: WalletPositionSnapshot) -> Dict[str, Dict[str, Any]]:
    positions = json.loads(snapshot.positions_json or "[]")
    return {str(position.get("coin", "")): position for position in positions if position.get("coin")}


def _dedupe_key(wallet_id: int, snapshot_id: int, symbol: str, signal_type: str, position: Dict[str, Any]) -> str:
    signed_size = round(_to_float(position.get("signed_size")), 8)
    entry_price = round(_to_float(position.get("entry_price")), 8)
    return f"{wallet_id}:{snapshot_id}:{symbol}:{signal_type}:{signed_size}:{entry_price}"


def _confidence_score(wallet: Wallet, metric: Optional[WalletMetric]) -> int:
    score = wallet.manual_score * 0.45
    if metric:
        score += min(metric.win_rate, 100) * 0.25
        score += min(metric.profit_factor * 12, 20)
        score += min(metric.trades_30d, 40) * 0.25
    else:
        score += 20
    return max(1, min(100, round(score)))


def _risk_score(position: Dict[str, Any], metric: Optional[WalletMetric]) -> int:
    leverage = _to_float(position.get("leverage"))
    position_value = abs(_to_float(position.get("position_value")))
    score = 20
    score += min(leverage * 5, 45)
    score += min(position_value / 2000, 25)
    if metric:
        score += max(0, 55 - metric.win_rate) * 0.25
        score += min(abs(metric.max_loss) / 50, 20)
    return max(1, min(100, round(score)))


def _reason(wallet: Wallet, metric: Optional[WalletMetric], leverage: float, risk_score: int) -> str:
    if metric:
        base = f"Wallet score {wallet.manual_score}, 30D win rate {metric.win_rate:.1f}%, profit factor {metric.profit_factor:.2f}."
    else:
        base = f"Wallet score {wallet.manual_score}. Metrics are still warming up."
    if leverage >= 10:
        return base + " Current leverage is high; simulation size is capped."
    if risk_score > 80:
        return base + " Risk score is above threshold, skip simulation."
    return base + " Signal is suitable for small paper simulation only."


def _risk_rule_block_reason(
    wallet: Wallet,
    metric: Optional[WalletMetric],
    rule: Optional[RiskRule],
    position: Dict[str, Any],
) -> Optional[str]:
    if not rule:
        return None
    blacklist_wallets = set(json.loads(rule.blacklist_wallets or "[]"))
    whitelist_wallets = set(json.loads(rule.whitelist_wallets or "[]"))
    blacklist_symbols = set(json.loads(rule.blacklist_symbols or "[]"))
    symbol = str(position.get("coin", ""))
    leverage = _to_float(position.get("leverage"))
    if wallet.address in blacklist_wallets or wallet.name in blacklist_wallets:
        return "wallet is blacklisted"
    if whitelist_wallets and wallet.address not in whitelist_wallets and wallet.name not in whitelist_wallets:
        return "wallet is not whitelisted"
    if symbol in blacklist_symbols:
        return "symbol is blacklisted"
    if wallet.manual_score < rule.min_wallet_score:
        return "wallet score below minimum"
    if leverage > rule.max_allowed_leverage:
        return "leverage above maximum"
    if metric:
        if metric.trades_30d < rule.min_trades:
            return "trade count below minimum"
        if metric.win_rate < rule.min_30d_win_rate:
            return "30D win rate below minimum"
    elif rule.min_trades > 0:
        return "wallet metrics unavailable"
    if rule.only_grade_a_or_s and _rough_grade(wallet, metric) not in {"S", "A"}:
        return "wallet grade below A"
    return None


def _rough_grade(wallet: Wallet, metric: Optional[WalletMetric]) -> str:
    score = wallet.manual_score
    if metric:
        score = score * 0.5 + metric.win_rate * 0.3 + min(metric.profit_factor * 10, 20)
    if score >= 85:
        return "S"
    if score >= 72:
        return "A"
    if score >= 58:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
