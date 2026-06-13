import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.market_data import WalletFill, WalletMetric, WalletPositionSnapshot
from app.models.wallet import Wallet


def calculate_wallet_metrics(db: Session, wallet: Wallet) -> WalletMetric:
    now = datetime.now(timezone.utc)
    fills = (
        db.query(WalletFill)
        .filter(WalletFill.wallet_id == wallet.id)
        .order_by(WalletFill.trade_time.asc())
        .all()
    )
    latest_position_snapshot = (
        db.query(WalletPositionSnapshot)
        .filter(WalletPositionSnapshot.wallet_id == wallet.id)
        .order_by(WalletPositionSnapshot.created_at.desc())
        .first()
    )

    total_trades = len(fills)
    trades_7d = len([fill for fill in fills if _as_utc(fill.trade_time) >= now - timedelta(days=7)])
    trades_30d = len([fill for fill in fills if _as_utc(fill.trade_time) >= now - timedelta(days=30)])
    realized_pnl = sum(fill.closed_pnl for fill in fills)
    pnl_values = [fill.closed_pnl for fill in fills if fill.closed_pnl != 0]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    win_rate = (len(wins) / len(pnl_values) * 100) if pnl_values else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0)
    max_loss = min(losses) if losses else 0
    unrealized_pnl = latest_position_snapshot.unrealized_pnl if latest_position_snapshot else 0
    current_positions_json = latest_position_snapshot.positions_json if latest_position_snapshot else "[]"
    last_trade_at = fills[-1].trade_time if fills else None

    metric = db.query(WalletMetric).filter(WalletMetric.wallet_id == wallet.id).first()
    if not metric:
        metric = WalletMetric(wallet_id=wallet.id)
        db.add(metric)

    metric.total_trades = total_trades
    metric.trades_7d = trades_7d
    metric.trades_30d = trades_30d
    metric.realized_pnl = round(realized_pnl, 6)
    metric.unrealized_pnl = round(unrealized_pnl, 6)
    metric.win_rate = round(win_rate, 2)
    metric.profit_factor = round(profit_factor, 4)
    metric.avg_win = round(avg_win, 6)
    metric.avg_loss = round(avg_loss, 6)
    metric.max_loss = round(max_loss, 6)
    metric.current_positions_json = current_positions_json
    metric.last_trade_at = last_trade_at
    metric.calculated_at = now
    db.commit()
    db.refresh(metric)
    return metric


def metric_to_dict(metric: Optional[WalletMetric]) -> Optional[dict[str, Any]]:
    if not metric:
        return None
    return {
        "total_trades": metric.total_trades,
        "trades_7d": metric.trades_7d,
        "trades_30d": metric.trades_30d,
        "realized_pnl": metric.realized_pnl,
        "unrealized_pnl": metric.unrealized_pnl,
        "win_rate": metric.win_rate,
        "profit_factor": metric.profit_factor,
        "avg_win": metric.avg_win,
        "avg_loss": metric.avg_loss,
        "max_loss": metric.max_loss,
        "current_positions": json.loads(metric.current_positions_json or "[]"),
        "last_trade_at": metric.last_trade_at,
        "calculated_at": metric.calculated_at,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
