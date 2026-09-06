"""Additive V3 records. Legacy event and paper tables are never updated here."""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class V3Run(Base):
    __tablename__ = "v3_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(64), unique=True)
    cutover_at: Mapped[datetime] = mapped_column(DateTime)
    high_water_id: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[str] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class V3Processing(Base):
    __tablename__ = "v3_signal_processing"
    __table_args__ = (UniqueConstraint("signal_id", "shadow_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("v3_runs.id"), index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    shadow_version: Mapped[str] = mapped_column(String(64))
    processing_status: Mapped[str] = mapped_column(
        String(24), default="pending", index=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    action: Mapped[str] = mapped_column(String(16), default="")
    shadow_trade_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(String(255), default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    evaluation_json: Mapped[str] = mapped_column(Text, default="{}")


class V3Position(Base):
    __tablename__ = "v3_shadow_positions"
    __table_args__ = (UniqueConstraint("run_id", "wallet_id", "symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("v3_runs.id"), index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    state: Mapped[str] = mapped_column(String(16), default="FLAT")
    trade_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    average_entry: Mapped[float] = mapped_column(Float, default=0)
    reference_entry: Mapped[float] = mapped_column(Float, default=0)
    margin: Mapped[float] = mapped_column(Float, default=0)
    leverage: Mapped[float] = mapped_column(Float, default=1)
    mark_price: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    marked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    quality: Mapped[str] = mapped_column(String(20), default="GOOD")


class V3Trade(Base):
    __tablename__ = "v3_shadow_trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("v3_runs.id"), index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("v3_shadow_positions.id"))
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"))
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0)
    fees: Mapped[float] = mapped_column(Float, default=0)
    slippage: Mapped[float] = mapped_column(Float, default=0)
    funding: Mapped[float] = mapped_column(Float, default=0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    funding_complete: Mapped[int] = mapped_column(Integer, default=0)


class V3Action(Base):
    __tablename__ = "v3_shadow_actions"
    __table_args__ = (UniqueConstraint("event_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("v3_runs.id"), index=True)
    processing_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("v3_signal_processing.id"), nullable=True
    )
    trade_id: Mapped[int] = mapped_column(ForeignKey("v3_shadow_trades.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(180))
    action: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[float] = mapped_column(Float, default=0)
    price: Mapped[float] = mapped_column(Float, default=0)
    reference_price: Mapped[float] = mapped_column(Float, default=0)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0)
    fees: Mapped[float] = mapped_column(Float, default=0)
    slippage: Mapped[float] = mapped_column(Float, default=0)
    funding: Mapped[float] = mapped_column(Float, default=0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0)
    position_after_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class V3Equity(Base):
    __tablename__ = "v3_shadow_equity_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("v3_runs.id"), index=True)
    realized_pnl: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float)
    total_pnl: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    used_margin: Mapped[float] = mapped_column(Float)
    quality: Mapped[str] = mapped_column(String(20))
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class V3WalletEvaluation(Base):
    __tablename__ = "v3_wallet_evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(12))
    copyability: Mapped[float] = mapped_column(Float)
    copy_label: Mapped[str] = mapped_column(String(24))
    quality: Mapped[str] = mapped_column(String(20))
    metrics_json: Mapped[str] = mapped_column(Text)
    as_of: Mapped[datetime] = mapped_column(DateTime, index=True)
    model_version: Mapped[str] = mapped_column(String(32), default="v3.0")


class V3Lifecycle(Base):
    __tablename__ = "v3_wallet_lifecycle"
    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    state: Mapped[str] = mapped_column(String(24))
    previous: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(255))
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("v3_wallet_evaluations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class V3Quality(Base):
    __tablename__ = "v3_data_quality"
    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(40), default="")
    category: Mapped[str] = mapped_column(String(40), index=True)
    source_log_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, unique=True
    )
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class V3Notification(Base):
    __tablename__ = "v3_notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(180), unique=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    message_id: Mapped[str] = mapped_column(String(80), default="")
    error: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class V3Job(Base):
    __tablename__ = "v3_jobs"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
