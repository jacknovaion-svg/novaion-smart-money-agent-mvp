import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main():
    db_path = ROOT / "data" / "novaion_p58_verify.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = "sqlite:///./data/novaion_p58_verify.db"
    os.environ["SCHEDULER_ENABLED"] = "false"

    from app.core.database import SessionLocal, init_db
    from app.models.ops import TaskLock
    from app.models.signal import PaperTrade, Signal
    from app.models.wallet import Wallet
    from app.services.ops_service import run_with_task_lock, update_task_heartbeat, validation_dashboard

    init_db()
    db = SessionLocal()
    try:
        seen = {}

        def long_task(heartbeat):
            first = db.query(TaskLock).filter(TaskLock.task_name == "p58_long_task").one().heartbeat_at
            update_task_heartbeat(db, "p58_long_task")
            second = db.query(TaskLock).filter(TaskLock.task_name == "p58_long_task").one().heartbeat_at
            seen["updated"] = second >= first
            heartbeat()
            return {"ok": True}

        result = run_with_task_lock(db, "p58_long_task", long_task)
        assert result["ok"] is True and seen["updated"] is True

        wallet = Wallet(address="0x1111111111111111111111111111111111111111", platform="hyperliquid", name="P58", status="active", manual_score=80)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
        s1 = Signal(wallet_id=wallet.id, platform="hyperliquid", symbol="BTC", signal_type="open", side="long", dedupe_key="p58-1")
        s2 = Signal(wallet_id=wallet.id, platform="hyperliquid", symbol="ETH", signal_type="open", side="long", dedupe_key="p58-2")
        db.add_all([s1, s2])
        db.commit()
        db.add(PaperTrade(signal_id=s1.id, wallet_id=wallet.id, symbol="BTC", side="long", entry_price=100, exit_price=105, size_usd=20, leverage=1, status="closed", pnl=1.0, net_pnl=1.0))
        db.add(PaperTrade(signal_id=s2.id, wallet_id=wallet.id, symbol="ETH", side="long", entry_price=100, exit_price=90, size_usd=20, leverage=1, status="closed", pnl=-2.0, net_pnl=-2.0))
        db.commit()
        dashboard = validation_dashboard(db)
        day = dashboard["days"][-1]
        for field in [
            "recommended_wallets_future_pnl",
            "watch_wallets_future_pnl",
            "all_candidates_baseline_pnl",
            "recommended_vs_baseline_comparison",
            "max_drawdown",
        ]:
            assert field in day, day

        seed = _verify_seed_audit()
        print(json.dumps({"ok": True, "heartbeat_updated": seen["updated"], "seed_audit": seed, "validation_fields": True}, ensure_ascii=False))
    finally:
        db.close()


def _verify_seed_audit():
    tmp = ROOT / "data" / "p58_seed"
    tmp.mkdir(parents=True, exist_ok=True)
    source = tmp / "source.txt"
    output = tmp / "discovery_wallets.txt"
    report = tmp / "fetch_seeds_report.md"
    source.write_text("\n".join([
        "0x1111111111111111111111111111111111111111",
        "0x1111111111111111111111111111111111111111",
        "0xBAD",
        "0x2222222222222222222222222222222222222222",
    ]), encoding="utf-8")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "fetch_seeds.py"),
        "--freedomcore-url",
        "http://127.0.0.1:1/not-running",
        "--source-file",
        str(source),
        "--skip-top",
        "0",
        "--limit",
        "10",
        "--output",
        str(output),
        "--report",
        str(report),
        "--json-report",
        str(tmp / "fetch_seeds_report.json"),
    ]
    env = os.environ.copy()
    env.pop("NANSEN_API_KEY", None)
    env.pop("APIFY_TOKEN", None)
    completed = subprocess.run(cmd, cwd=ROOT, env=env, check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["found_count"] == 4, payload
    assert payload["valid_count"] == 3, payload
    assert payload["invalid_count"] == 1, payload
    assert payload["duplicate_count"] == 1, payload
    assert payload["inserted_count"] == 2, payload
    text = report.read_text(encoding="utf-8")
    assert "found_count" in text and "duplicate_count" in text and ("warnings" in text or "Warnings" in text)
    return {key: payload[key] for key in ["found_count", "valid_count", "invalid_count", "duplicate_count", "inserted_count"]}


if __name__ == "__main__":
    main()
