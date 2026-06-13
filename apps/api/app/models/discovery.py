from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (UniqueConstraint("address", name="uq_discovery_candidate_address"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    address: Mapped[str] = mapped_column(String(128), index=True)
    platform: Mapped[str] = mapped_column(String(32), default="hyperliquid")
    source: Mapped[str] = mapped_column(String(120), default="unknown")
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    roi: Mapped[float] = mapped_column(Float, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    total_pnl: Mapped[float] = mapped_column(Float, default=0)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    trades_7d: Mapped[int] = mapped_column(Integer, default=0)
    trades_30d: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0)
    profit_factor: Mapped[float] = mapped_column(Float, default=0)
    gross_profit: Mapped[float] = mapped_column(Float, default=0)
    avg_leverage: Mapped[float] = mapped_column(Float, default=0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    grade: Mapped[str] = mapped_column(String(20), default="Watch", index=True)
    aggregation_confidence: Mapped[str] = mapped_column(String(20), default="low")
    metrics_estimated: Mapped[int] = mapped_column(Integer, default=1)
    funding_included: Mapped[int] = mapped_column(Integer, default=0)
    drawdown_estimation_method: Mapped[str] = mapped_column(String(80), default="current_account_value")
    hard_filter_pass: Mapped[int] = mapped_column(Integer, default=0)
    soft_watch_eligible: Mapped[int] = mapped_column(Integer, default=0)
    failed_reasons: Mapped[str] = mapped_column(Text, default="[]")
    account_value: Mapped[float] = mapped_column(Float, default=0)
    active_positions: Mapped[int] = mapped_column(Integer, default=0)
    best_symbol: Mapped[str] = mapped_column(String(40), default="")
    worst_symbol: Mapped[str] = mapped_column(String(40), default="")
    recommendation: Mapped[str] = mapped_column(String(255), default="collect_more_data")
    reason: Mapped[str] = mapped_column(Text, default="")
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    added_wallet_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    scanned_count: Mapped[int] = mapped_column(Integer, default=0)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    evaluated_count: Mapped[int] = mapped_column(Integer, default=0)
    recommended_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    no_activity_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_added_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
