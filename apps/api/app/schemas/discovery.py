from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DiscoveryCandidateRead(BaseModel):
    id: int
    address: str
    platform: str
    source: str
    status: str
    score: int
    roi: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    total_trades: int
    trades_7d: int
    trades_30d: int
    win_rate: float
    profit_factor: float
    gross_profit: float
    avg_leverage: float
    max_drawdown: float
    risk_score: int
    grade: str
    aggregation_confidence: str
    metrics_estimated: int
    funding_included: int
    drawdown_estimation_method: str
    hard_filter_pass: int
    soft_watch_eligible: int
    failed_reasons: str
    account_value: float
    active_positions: int
    best_symbol: str
    worst_symbol: str
    recommendation: str
    reason: str
    failure_reason: str
    added_wallet_id: Optional[int]
    discovered_at: datetime
    evaluated_at: Optional[datetime]


class DiscoveryRunRead(BaseModel):
    id: int
    status: str
    source_count: int
    scanned_count: int
    discovered_count: int
    evaluated_count: int
    recommended_count: int
    failed_count: int
    no_activity_count: int
    auto_added_count: int
    error_message: str
    started_at: datetime
    finished_at: Optional[datetime]


class DiscoverySummaryRead(BaseModel):
    total_candidates: int
    recommended: int
    added: int
    approved: int
    failed: int
    no_activity: int
    top_candidates: list[DiscoveryCandidateRead]
    recent_runs: list[DiscoveryRunRead]


class DiscoveryImportRequest(BaseModel):
    content: str
    source_type: str = "txt"
    source_name: str = "manual"


class DiscoveryImportResult(BaseModel):
    total_count: int
    valid_count: int
    invalid_count: int
    duplicate_count: int
    inserted_count: int
