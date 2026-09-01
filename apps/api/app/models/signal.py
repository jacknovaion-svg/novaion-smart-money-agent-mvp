from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_signal_dedupe_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), default="hyperliquid")
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    signal_type: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    source_size: Mapped[float] = mapped_column(Float, default=0)
    source_leverage: Mapped[float] = mapped_column(Float, default=0)
    source_entry_price: Mapped[float] = mapped_column(Float, default=0)
    current_price: Mapped[float] = mapped_column(Float, default=0)
    confidence_score: Mapped[int] = mapped_column(Integer, default=50)
    risk_score: Mapped[int] = mapped_column(Integer, default=50)
    suggested_action: Mapped[str] = mapped_column(String(255), default="Only simulate. Do not live trade.")
    suggested_size_usd: Mapped[float] = mapped_column(Float, default=20)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    source_trade_id: Mapped[str] = mapped_column(String(180), default="")
    dedupe_key: Mapped[str] = mapped_column(String(220), index=True)
    telegram_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    entry_price: Mapped[float] = mapped_column(Float, default=0)
    exit_price: Mapped[float] = mapped_column(Float, default=0)
    size_usd: Mapped[float] = mapped_column(Float, default=20)
    leverage: Mapped[float] = mapped_column(Float, default=1)
    stop_loss: Mapped[float] = mapped_column(Float, default=0)
    take_profit: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    pnl: Mapped[float] = mapped_column(Float, default=0)
    raw_pnl: Mapped[float] = mapped_column(Float, default=0)
    fees: Mapped[float] = mapped_column(Float, default=0)
    slippage_adjustment: Mapped[float] = mapped_column(Float, default=0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0)
    mark_price: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl_pct: Mapped[float] = mapped_column(Float, default=0)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SignalPerformance(Base):
    __tablename__ = "signal_performance"
    __table_args__ = (UniqueConstraint("signal_id", name="uq_signal_performance_signal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    entry_price: Mapped[float] = mapped_column(Float, default=0)
    return_5m: Mapped[float] = mapped_column(Float, default=0)
    return_15m: Mapped[float] = mapped_column(Float, default=0)
    return_1h: Mapped[float] = mapped_column(Float, default=0)
    return_4h: Mapped[float] = mapped_column(Float, default=0)
    return_24h: Mapped[float] = mapped_column(Float, default=0)
    max_favorable: Mapped[float] = mapped_column(Float, default=0)
    max_adverse: Mapped[float] = mapped_column(Float, default=0)
    hit_stop_loss: Mapped[int] = mapped_column(Integer, default=0)
    hit_take_profit: Mapped[int] = mapped_column(Integer, default=0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    last_price: Mapped[float] = mapped_column(Float, default=0)
    last_evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class RiskRule(Base):
    __tablename__ = "risk_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    blacklist_wallets: Mapped[str] = mapped_column(Text, default="[]")
    whitelist_wallets: Mapped[str] = mapped_column(Text, default="[]")
    blacklist_symbols: Mapped[str] = mapped_column(Text, default="[]")
    min_wallet_score: Mapped[int] = mapped_column(Integer, default=50)
    max_allowed_leverage: Mapped[float] = mapped_column(Float, default=10)
    min_trades: Mapped[int] = mapped_column(Integer, default=10)
    min_30d_win_rate: Mapped[float] = mapped_column(Float, default=45)
    only_grade_a_or_s: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("report_date", name="uq_daily_report_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    report_date: Mapped[str] = mapped_column(String(16), index=True)
    signal_count: Mapped[int] = mapped_column(Integer, default=0)
    simulated_pnl: Mapped[float] = mapped_column(Float, default=0)
    best_wallet: Mapped[str] = mapped_column(String(120), default="")
    worst_wallet: Mapped[str] = mapped_column(String(120), default="")
    keep_wallets_json: Mapped[str] = mapped_column(Text, default="[]")
    remove_wallets_json: Mapped[str] = mapped_column(Text, default="[]")
    focus_json: Mapped[str] = mapped_column(Text, default="[]")
    live_test_recommendation: Mapped[str] = mapped_column(String(255), default="Not recommended")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    telegram_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
