import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


GOOD = "0x1111111111111111111111111111111111111111"
FAIL = "0x2222222222222222222222222222222222222222"
EXISTING = "0x3333333333333333333333333333333333333333"


def main():
    db_path = ROOT / "data" / "novaion_discovery_pipeline_verify.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = "sqlite:///./data/novaion_discovery_pipeline_verify.db"
    os.environ["SCHEDULER_ENABLED"] = "false"
    os.environ["DISCOVERY_AUTO_ADD_ENABLED"] = "false"
    os.environ["DISCOVERY_MIN_SCORE_TO_ADD"] = "80"

    from app.core.database import SessionLocal, init_db
    from app.models.discovery import DiscoveryCandidate, DiscoveryRun
    from app.models.wallet import Wallet
    from app.services import discovery_service
    from app.services.discovery_service import (
        approve_candidate,
        discovery_summary,
        evaluate_candidates,
        import_candidates_from_csv,
        import_candidates_from_text,
        run_wallet_discovery,
    )

    init_db()
    db = SessionLocal()
    try:
        existing = Wallet(
            address=EXISTING,
            platform="hyperliquid",
            name="Existing Watchlist",
            tags="verify",
            manual_score=90,
            status="active",
            notes="already watched",
        )
        db.add(existing)
        db.commit()

        imported = import_candidates_from_text(db, f"{GOOD}\n{GOOD}\n0xBAD\n{EXISTING}\n", "verify-txt")
        assert imported["valid_count"] == 3, imported
        assert imported["invalid_count"] == 1, imported
        assert imported["duplicate_count"] == 2, imported
        assert imported["inserted_count"] == 1, imported

        csv_imported = import_candidates_from_csv(db, f"address\n{FAIL}\n0xBADCSV\n", "verify-csv")
        assert csv_imported["inserted_count"] == 1, csv_imported
        assert csv_imported["invalid_count"] == 1, csv_imported

        discovery_service.HyperliquidApiClient = _FakeHyperliquidClient
        evaluated = evaluate_candidates(db, limit=10)
        assert evaluated == 1, evaluated
        good = db.query(DiscoveryCandidate).filter(DiscoveryCandidate.address == GOOD).one()
        failed = db.query(DiscoveryCandidate).filter(DiscoveryCandidate.address == FAIL).one()
        assert good.status == "evaluated", good.status
        assert good.soft_watch_eligible == 1, good.soft_watch_eligible
        assert good.score < 85, good.score
        assert failed.status == "failed", failed.status
        assert failed.failure_reason == "api_error", failed.failure_reason

        assert db.query(Wallet).filter(Wallet.address == GOOD).count() == 0
        wallet = approve_candidate(db, good.id)
        assert wallet.address == GOOD
        assert db.query(Wallet).filter(Wallet.address == GOOD).count() == 1

        discovery_service.discover_candidate_addresses = lambda: {GOOD: "verify-run", FAIL: "verify-run"}
        run_wallet_discovery(db)
        assert db.query(DiscoveryRun).count() >= 1
        summary = discovery_summary(db)

        frontend_build = _frontend_build_check()
        result = {
            "ok": True,
            "imported": imported,
            "csv_imported": csv_imported,
            "recommended": summary["recommended"],
            "approved_wallet_id": wallet.id,
            "discovery_runs": db.query(DiscoveryRun).count(),
            "frontend_build": frontend_build,
        }
        print(json.dumps(result, ensure_ascii=False))
    finally:
        db.close()


class _FakeHyperliquidClient:
    def __init__(self, db):
        self.db = db

    def get_user_fills(self, address):
        if address == FAIL:
            raise RuntimeError("api_error: synthetic failure")
        return self._fills()

    def get_user_fills_by_time(self, address, start_time, end_time):
        if address == FAIL:
            raise RuntimeError("api_error: synthetic failure")
        return self._fills(end_time)

    def get_clearinghouse_state(self, address):
        return {
            "marginSummary": {"accountValue": "5000"},
            "assetPositions": [
                {"position": {"coin": "BTC", "unrealizedPnl": "250", "leverage": {"value": "3"}}},
            ],
        }

    def get_open_orders(self, address):
        return []

    def _fills(self, now_ms=1_800_000_000_000):
        rows = []
        for idx in range(75):
            rows.append({"coin": "BTC", "closedPnl": "80", "time": now_ms - idx * 60_000})
        for idx in range(5):
            rows.append({"coin": "ETH", "closedPnl": "-20", "time": now_ms - (idx + 80) * 60_000})
        return rows


def _frontend_build_check():
    web_dir = ROOT / "apps" / "web"
    if not web_dir.exists() or not (web_dir / "package.json").exists():
        return {"status": "skipped", "reason": "react frontend package not present"}
    if not shutil.which("npm"):
        return {"status": "skipped", "reason": "npm not installed in this shell"}
    completed = subprocess.run(["npm", "run", "build"], cwd=web_dir, check=False, capture_output=True, text=True)
    return {"status": "ok" if completed.returncode == 0 else "failed", "returncode": completed.returncode}


if __name__ == "__main__":
    main()
