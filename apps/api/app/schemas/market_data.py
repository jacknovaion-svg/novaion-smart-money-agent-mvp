from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class WalletMetricRead(BaseModel):
    total_trades: int
    trades_7d: int
    trades_30d: int
    realized_pnl: float
    unrealized_pnl: float
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    max_loss: float
    current_positions: list[dict[str, Any]]
    last_trade_at: Optional[datetime]
    calculated_at: datetime


class WalletFillRead(BaseModel):
    id: int
    source_trade_id: str
    coin: str
    side: str
    price: float
    size: float
    closed_pnl: float
    fee: float
    trade_time: datetime

    model_config = {"from_attributes": True}


class WalletMarketDataRead(BaseModel):
    fills: list[WalletFillRead]
    positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]
    metric: Optional[WalletMetricRead]


class WalletRankingItem(BaseModel):
    wallet_id: int
    name: str
    address: str
    tags: str
    manual_score: int
    total_trades: int
    trades_30d: int
    realized_pnl: float
    unrealized_pnl: float
    win_rate: float
    profit_factor: float
    last_trade_at: Optional[datetime]


class MarketRefreshResult(BaseModel):
    synced_wallets: int
    fills_inserted: int
    errors: list[str]
