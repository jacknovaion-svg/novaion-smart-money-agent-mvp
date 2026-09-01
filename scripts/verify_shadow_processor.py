"""Focused isolated tests for the V2 signal-to-shadow processor."""

import os
import tempfile
from datetime import datetime, timedelta, timezone


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="novaion-shadow-") as tmp:
        os.environ.update(
            {
                "DATABASE_URL": f"sqlite:///{tmp}/shadow.db",
                "V2_ALPHA_VALIDATION_ENABLED": "true",
                "SHADOW_TRADING_ENABLED": "true",
                "VALIDATION_MODE": "true",
                "PAPER_TRADING_CUTOVER_AT": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            }
        )
        from app.core.database import Base, SessionLocal, engine
        from app.models.signal import Signal
        from app.models.v2_validation import ShadowTrade, ShadowTradeAction
        from app.models.wallet import Wallet
        from app.services.v2_validation_service import process_new_signals_for_shadow

        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        wallet = Wallet(address="0x" + "1" * 40, platform="hyperliquid", name="shadow-test", status="active")
        db.add(wallet)
        db.flush()
        now = datetime.now(timezone.utc)

        def add_signal(kind, price, side="long", key=None):
            signal = Signal(
                wallet_id=wallet.id,
                symbol="BTC",
                signal_type=kind,
                side=side,
                current_price=price,
                source_entry_price=price,
                source_leverage=2,
                suggested_size_usd=20,
                created_at=now,
                dedupe_key=key or f"shadow-{kind}-{price}",
            )
            db.add(signal)
            db.flush()
            return signal

        opened = add_signal("open", 100, key="shadow-open")
        db.commit()
        first = process_new_signals_for_shadow(db)
        trade = db.query(ShadowTrade).one()
        assert first["opened"] == 1 and trade.status == "open" and trade.size_usd == 20

        assert process_new_signals_for_shadow(db)["processed"] == 0
        duplicate = add_signal("open", 101, key="shadow-duplicate")
        db.commit()
        result = process_new_signals_for_shadow(db)
        assert result["ignored"] == 1 and duplicate.status == "ignored" and db.query(ShadowTrade).count() == 1

        added = add_signal("add", 110, key="shadow-add")
        db.commit()
        result = process_new_signals_for_shadow(db)
        assert result["added"] == 1 and trade.size_usd == 40

        reduced = add_signal("reduce", 120, key="shadow-reduce")
        db.commit()
        result = process_new_signals_for_shadow(db)
        assert result["reduced"] == 1 and trade.size_usd == 20 and trade.net_pnl != 0

        closed = add_signal("close", 130, side="close", key="shadow-close")
        db.commit()
        result = process_new_signals_for_shadow(db)
        assert result["closed"] == 1 and trade.status == "closed" and trade.size_usd == 0
        assert db.query(ShadowTradeAction).count() == 5

        assert process_new_signals_for_shadow(db)["processed"] == 0
        assert db.query(ShadowTradeAction).filter(ShadowTradeAction.signal_id == closed.id).count() == 1
        db.close()
        engine.dispose()
        print({"tests_total": 8, "tests_passed": 8, "tests_failed": 0})


if __name__ == "__main__":
    main()
