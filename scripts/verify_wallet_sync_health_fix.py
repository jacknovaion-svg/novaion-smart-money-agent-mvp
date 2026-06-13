import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main():
    db_path = ROOT / "data" / "novaion_wallet_sync_health_fix.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = "sqlite:///./data/novaion_wallet_sync_health_fix.db"
    os.environ["SCHEDULER_ENABLED"] = "false"
    os.environ["VALIDATION_MODE"] = "true"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test"
    os.environ["TELEGRAM_CHAT_ID"] = "test"

    from app.core.config import get_settings
    from app.core.database import SessionLocal, init_db
    from app.models.discovery import DiscoveryCandidate, DiscoveryRun
    from app.models.market_data import SyncState
    from app.models.wallet import Wallet
    from app.services import wallet_sync_service
    from app.services.health_service import system_health
    from app.services.ops_service import validation_readiness

    get_settings.cache_clear()
    init_db()
    db = SessionLocal()
    try:
        stale_at = datetime.now(timezone.utc) - timedelta(hours=1)
        wallets = []
        for idx in range(5):
            wallets.append(
                Wallet(
                    address=f"0x{idx + 1:040x}",
                    platform="hyperliquid",
                    name=f"Health Fix Verify {idx + 1}",
                    tags="",
                    manual_score=80,
                    status="active",
                )
            )
        db.add_all(wallets)
        db.commit()
        wallet = wallets[0]
        db.refresh(wallet)
        state = SyncState(
            wallet_id=wallet.id,
            sync_type="hyperliquid_fills",
            cursor_value="1",
            status="ok",
            error_message="",
            updated_at=stale_at,
        )
        db.add(state)
        db.add(
            DiscoveryRun(
                status="ok",
                source_count=20,
                scanned_count=20,
                discovered_count=20,
                evaluated_count=20,
                finished_at=datetime.now(timezone.utc),
            )
        )
        for idx in range(20):
            db.add(
                DiscoveryCandidate(
                    address=f"0x{idx + 2:040x}",
                    platform="hyperliquid",
                    source="verify",
                    status="candidate",
                )
            )
        db.commit()

        class FakeHyperliquidApiClient:
            def __init__(self, _db):
                pass

            def get_all_mids(self):
                return {"BTC": 100}

            def get_user_fills_by_time(self, _address, _start_ms, _end_ms):
                return []

            def get_clearinghouse_state(self, _address):
                return {"assetPositions": [], "marginSummary": {"accountValue": "1000"}}

            def get_open_orders(self, _address):
                return []

        wallet_sync_service.HyperliquidApiClient = FakeHyperliquidApiClient
        wallet_sync_service.calculate_wallet_metrics = lambda _db, _wallet: None
        wallet_sync_service.generate_signals_for_wallet = lambda _db, _wallet, _mids: []

        result = wallet_sync_service.sync_wallet_market_data(db, wallet)
        db.refresh(state)
        health = system_health(db)
        readiness = validation_readiness(db, {**health, "scheduler_status": "running", "overall_status": "ok"})

        assert result["fills_inserted"] == 0, result
        updated_at = state.updated_at.replace(tzinfo=timezone.utc) if state.updated_at.tzinfo is None else state.updated_at
        assert updated_at > stale_at, (state.updated_at, stale_at)
        assert health["wallet_sync_status"] == "ok", health
        assert health["overall_status"] != "critical", health
        assert readiness["can_start_7_day_validation"] is True, readiness

        print(
            json.dumps(
                {
                    "ok": True,
                    "last_wallet_sync_at_updated": True,
                    "wallet_sync_status": health["wallet_sync_status"],
                    "health_status": health["overall_status"],
                    "readiness_recalculated": readiness["can_start_7_day_validation"],
                    "blocking_reasons": readiness["blocking_reasons"],
                },
                ensure_ascii=False,
                default=str,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
