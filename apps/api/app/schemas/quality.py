from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class SignalPerformanceRead(BaseModel):
    signal_id: int
    wallet_id: int
    symbol: str
    side: str
    entry_price: float
    return_5m: float
    return_15m: float
    return_1h: float
    return_4h: float
    return_24h: float
    max_favorable: float
    max_adverse: float
    hit_stop_loss: int
    hit_take_profit: int
    sample_count: int
    last_price: float
    last_evaluated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class WalletContributionRead(BaseModel):
    wallet_id: int
    wallet_name: str
    signal_count: int
    simulated_pnl: float
    win_rate: float
    max_drawdown: float
    best_symbol: Optional[str]
    worst_symbol: Optional[str]
    grade: str
    keep_recommendation: str


class SignalTypeAnalysisRead(BaseModel):
    signal_type: str
    signal_count: int
    avg_return_24h: float
    win_rate_24h: float
    avg_max_favorable: float
    avg_max_adverse: float


class RiskRuleRead(BaseModel):
    blacklist_wallets: list[str]
    whitelist_wallets: list[str]
    blacklist_symbols: list[str]
    min_wallet_score: int
    max_allowed_leverage: float
    min_trades: int
    min_30d_win_rate: float
    only_grade_a_or_s: bool


class RiskRuleUpdate(RiskRuleRead):
    pass


class DailyReportRead(BaseModel):
    id: int
    report_date: str
    signal_count: int
    simulated_pnl: float
    best_wallet: str
    worst_wallet: str
    keep_wallets: list[str]
    remove_wallets: list[str]
    focus: list[str]
    live_test_recommendation: str
    payload: dict[str, Any]
    created_at: datetime


class QualityDashboardRead(BaseModel):
    seven_day_curve: list[dict[str, Any]]
    wallet_rankings: list[WalletContributionRead]
    signal_type_analysis: list[SignalTypeAnalysisRead]
    signal_win_rate: float
    max_drawdown: float
    system_status: str
    live_test_recommendation: str
