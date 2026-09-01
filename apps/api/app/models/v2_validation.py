from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    starting_balance: Mapped[float] = mapped_column(Float, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0)
    equity: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(32), default="paper_trading")


class DataQualityEvent(Base):
    __tablename__ = "data_quality_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("signals.id"), nullable=True, index=True)
    wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallets.id"), nullable=True, index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    quality_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class ShadowTrade(Base):
    __tablename__ = "shadow_trades"
    __table_args__ = (UniqueConstraint("signal_id", name="uq_shadow_trade_signal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    size_usd: Mapped[float] = mapped_column(Float, default=0)
    leverage: Mapped[float] = mapped_column(Float, default=1)
    entry_price: Mapped[float] = mapped_column(Float, default=0)
    exit_price: Mapped[float] = mapped_column(Float, default=0)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0)
    fees: Mapped[float] = mapped_column(Float, default=0)
    slippage_adjustment: Mapped[float] = mapped_column(Float, default=0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0)
    mark_price: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    quality_status: Mapped[str] = mapped_column(String(32), default="clean")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ShadowTradeAction(Base):
    """One immutable audit row per post-cutover signal handled by Shadow Trading."""

    __tablename__ = "shadow_trade_actions"
    __table_args__ = (UniqueConstraint("signal_id", name="uq_shadow_trade_action_signal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    shadow_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shadow_trades.id"), nullable=True, index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(16), default="long")
    action_type: Mapped[str] = mapped_column(String(16), index=True)
    size_usd: Mapped[float] = mapped_column(Float, default=0)
    entry_price: Mapped[float] = mapped_column(Float, default=0)
    exit_price: Mapped[float] = mapped_column(Float, default=0)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0)
    fees: Mapped[float] = mapped_column(Float, default=0)
    slippage_adjustment: Mapped[float] = mapped_column(Float, default=0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="processed")
    reason: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class PaperTradeAction(Base):
    __tablename__ = "paper_trade_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    paper_trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("paper_trades.id"), nullable=True, index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    action_type: Mapped[str] = mapped_column(String(16), index=True)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0)
    fees: Mapped[float] = mapped_column(Float, default=0)
    slippage_adjustment: Mapped[float] = mapped_column(Float, default=0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0)
    quality_status: Mapped[str] = mapped_column(String(32), default="clean")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
