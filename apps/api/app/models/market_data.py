from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WalletFill(Base):
    __tablename__ = "wallet_fills"
    __table_args__ = (UniqueConstraint("wallet_id", "source_trade_id", name="uq_wallet_fill_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    source_trade_id: Mapped[str] = mapped_column(String(160), index=True)
    coin: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(16), default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    size: Mapped[float] = mapped_column(Float, default=0)
    closed_pnl: Mapped[float] = mapped_column(Float, default=0)
    fee: Mapped[float] = mapped_column(Float, default=0)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    trade_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class WalletPositionSnapshot(Base):
    __tablename__ = "wallet_position_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    positions_json: Mapped[str] = mapped_column(Text, default="[]")
    account_value: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class WalletOrderSnapshot(Base):
    __tablename__ = "wallet_order_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    raw_json: Mapped[str] = mapped_column(Text, default="[]")
    open_order_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class WalletMetric(Base):
    __tablename__ = "wallet_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), unique=True, index=True)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    trades_7d: Mapped[int] = mapped_column(Integer, default=0)
    trades_30d: Mapped[int] = mapped_column(Integer, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0)
    profit_factor: Mapped[float] = mapped_column(Float, default=0)
    avg_win: Mapped[float] = mapped_column(Float, default=0)
    avg_loss: Mapped[float] = mapped_column(Float, default=0)
    max_loss: Mapped[float] = mapped_column(Float, default=0)
    current_positions_json: Mapped[str] = mapped_column(Text, default="[]")
    last_trade_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class SyncState(Base):
    __tablename__ = "sync_states"
    __table_args__ = (UniqueConstraint("wallet_id", "sync_type", name="uq_sync_state_wallet_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), index=True)
    sync_type: Mapped[str] = mapped_column(String(80), index=True)
    cursor_value: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(32), default="idle")
    error_message: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
