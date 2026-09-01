"""Focused V2 validation checks using an isolated temporary SQLite database."""

import os
import tempfile
from datetime import datetime, timedelta, timezone


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="novaion-v2-") as tmp:
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/v2.db"
        os.environ["V2_ALPHA_VALIDATION_ENABLED"] = "true"
        os.environ["SHADOW_TRADING_ENABLED"] = "true"
        os.environ["VALIDATION_MODE"] = "true"
        os.environ["PAPER_ACCOUNT_STARTING_BALANCE_USD"] = "100"
        from app.core.database import Base, SessionLocal, engine
        from app.models.signal import PaperTrade, Signal
        from app.models.v2_validation import DataQualityEvent, ShadowTrade
        from app.models.wallet import Wallet
        from app.services.v2_validation_service import (
            alpha_attribution,
            close_shadow_trade,
            create_shadow_trade,
            equity_curve,
            holding_time_stats,
            max_drawdown,
            record_data_quality_event,
            record_equity_snapshot,
            shadow_summary,
        )

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        passed = 0
        total = 0

        def check(name: str, condition: bool) -> None:
            nonlocal passed, total
            total += 1
            if not condition:
                raise AssertionError(name)
            passed += 1

        now = datetime.now(timezone.utc)
        wallet = Wallet(address="0x" + "1" * 40, platform="hyperliquid", name="V2 wallet", status="active")
        db.add(wallet)
        db.flush()
        signal = Signal(
            wallet_id=wallet.id,
            symbol="BTC",
            signal_type="open",
            side="long",
            current_price=100,
            source_entry_price=100,
            source_leverage=2,
            suggested_size_usd=20,
            dedupe_key="v2-signal-1",
        )
        db.add(signal)
        db.flush()
        trade = PaperTrade(
            signal_id=signal.id,
            wallet_id=wallet.id,
            symbol="BTC",
            side="long",
            entry_price=100,
            size_usd=20,
            leverage=1,
            status="closed",
            pnl=10,
            net_pnl=10,
            raw_pnl=12,
            fees=1,
            slippage_adjustment=1,
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
        )
        db.add(trade)
        db.commit()

        first = record_equity_snapshot(db, captured_at=now - timedelta(minutes=2))
        trade.pnl = 5
        trade.net_pnl = 5
        db.commit()
        second = record_equity_snapshot(db, captured_at=now)
        curve = equity_curve(db)
        check("equity curve keeps history", len(curve) == 2 and second.equity == 105)
        check("drawdown returns complete result", max_drawdown(curve)["amount"] == 5)
        check("holding time average", holding_time_stats([trade])["average_seconds"] == 3600)
        check("alpha attribution wallet", alpha_attribution(db)["wallets"][0]["net_pnl"] == 5)

        quality = record_data_quality_event(db, "hyperliquid_429", signal=signal, details={"retry": 3})
        check("quality marker persisted", db.query(DataQualityEvent).count() == 1 and quality.signal_id == signal.id)

        shadow_signal = Signal(
            wallet_id=wallet.id,
            symbol="ETH",
            signal_type="open",
            side="short",
            current_price=200,
            source_entry_price=200,
            source_leverage=3,
            suggested_size_usd=10,
            dedupe_key="v2-shadow-signal",
        )
        db.add(shadow_signal)
        db.commit()
        shadow = create_shadow_trade(db, shadow_signal)
        same = create_shadow_trade(db, shadow_signal)
        check("shadow trade idempotent", shadow.id == same.id and db.query(ShadowTrade).count() == 1)
        closed = close_shadow_trade(db, shadow, 190)
        check("shadow close net pnl", closed.status == "closed" and closed.net_pnl > 0)
        check("shadow summary", shadow_summary(db)["closed_trades"] == 1)
        db.close()
        engine.dispose()
        print({"tests_total": total, "tests_passed": passed, "tests_failed": total - passed})


if __name__ == "__main__":
    main()
