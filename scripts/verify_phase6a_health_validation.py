import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main():
    db_path = ROOT / "data" / "novaion_phase6a_verify.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = "sqlite:///./data/novaion_phase6a_verify.db"
    os.environ["SCHEDULER_ENABLED"] = "false"
    os.environ["VALIDATION_MODE"] = "true"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test"
    os.environ["TELEGRAM_CHAT_ID"] = "test"

    from app.core.config import get_settings
    from app.core.database import SessionLocal, init_db
    from app.models.signal import Signal
    from app.models.wallet import Wallet
    from app.services import telegram_service
    from app.services.health_service import system_health
    from app.services.ops_service import record_hyperliquid_metric, run_with_task_lock, validation_dashboard, validation_readiness
    from app.services.paper_trading_service import add_signal_to_paper, close_paper_trade

    get_settings.cache_clear()
    init_db()
    db = SessionLocal()
    try:
        wallet = Wallet(address="0x1111111111111111111111111111111111111111", platform="hyperliquid", name="Verify", tags="", manual_score=80, status="active")
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
        signal = Signal(
            wallet_id=wallet.id,
            platform="hyperliquid",
            symbol="BTC",
            signal_type="open",
            side="long",
            source_size=1000,
            source_leverage=2,
            source_entry_price=100,
            current_price=100,
            confidence_score=70,
            risk_score=30,
            suggested_size_usd=20,
            source_trade_id="verify",
            dedupe_key="verify-phase6a",
        )
        db.add(signal)
        db.commit()
        db.refresh(signal)
        trade = add_signal_to_paper(db, signal)
        assert trade.entry_price == 100.1, trade.entry_price
        closed = close_paper_trade(db, trade, 110)
        assert closed.raw_pnl > closed.net_pnl, (closed.raw_pnl, closed.net_pnl)
        assert closed.fees > 0, closed.fees

        first = run_with_task_lock(db, "verify_lock", lambda: {"ok": True})
        assert first["ok"] is True, first

        record_hyperliquid_metric(db, success=True, latency_ms=100)
        record_hyperliquid_metric(db, success=False, latency_ms=200, error="timeout")

        calls = {"count": 0}

        class _Response:
            def raise_for_status(self):
                return None

        def fake_post(*args, **kwargs):
            calls["count"] += 1
            return _Response()

        telegram_service.httpx.post = fake_post
        assert telegram_service.send_ops_alert(db, "Wallet Sync Failed", "verify") is True
        assert telegram_service.send_ops_alert(db, "Wallet Sync Failed", "verify again") is False
        assert calls["count"] == 1, calls

        health = system_health(db)
        readiness = validation_readiness(db, health)
        dashboard = validation_dashboard(db)
        assert "api_status" in health and "hyperliquid_api" in health, health
        assert readiness["telegram_configured"] is True, readiness
        assert readiness["can_start_7_day_validation"] is False, readiness
        assert "wallets_count_below_5" in readiness["blocking_reasons"], readiness
        assert dashboard["validation_mode"] is True, dashboard
        assert len(dashboard["days"]) == 7, dashboard

        print(json.dumps({"ok": True, "health": health["overall_status"], "readiness": readiness["can_start_7_day_validation"], "blocking_reasons": readiness["blocking_reasons"], "net_pnl": closed.net_pnl}, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
