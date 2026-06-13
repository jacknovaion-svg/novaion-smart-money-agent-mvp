from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SignalRead(BaseModel):
    id: int
    wallet_id: int
    platform: str
    symbol: str
    signal_type: str
    side: str
    source_size: float
    source_leverage: float
    source_entry_price: float
    current_price: float
    confidence_score: int
    risk_score: int
    suggested_action: str
    suggested_size_usd: float
    reason: str
    status: str
    source_trade_id: str
    created_at: datetime
    wallet_name: Optional[str] = None
    wallet_tags: Optional[str] = None

    model_config = {"from_attributes": True}


class SignalUpdate(BaseModel):
    status: str


class PaperTradeRead(BaseModel):
    id: int
    signal_id: int
    wallet_id: int
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size_usd: float
    leverage: float
    stop_loss: float
    take_profit: float
    status: str
    pnl: float
    raw_pnl: float
    fees: float
    slippage_adjustment: float
    net_pnl: float
    opened_at: datetime
    closed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PaperAccountSummary(BaseModel):
    starting_balance: float
    current_equity: float
    today_pnl: float
    total_pnl: float
    win_rate: float
    max_drawdown: float
    open_positions: int
    closed_trades: int
    best_wallet: Optional[str]
    worst_wallet: Optional[str]
    recent_trades: list[PaperTradeRead]
