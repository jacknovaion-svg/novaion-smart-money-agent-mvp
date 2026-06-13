import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main():
    os.environ.setdefault("DATABASE_URL", "sqlite:///./data/novaion_full_verify.db")
    os.environ.setdefault("SCHEDULER_ENABLED", "false")

    from app.core.database import SessionLocal, init_db
    from app.models.market_data import WalletMetric, WalletPositionSnapshot
    from app.models.signal import PaperTrade, Signal
    from app.models.wallet import Wallet
    from app.services import discovery_service
    from app.services.discovery_service import (
        auto_add_recommended_candidates,
        discovery_summary,
        evaluate_candidates,
        upsert_candidates,
    )
    from app.services.paper_trading_service import add_signal_to_paper, close_from_signal, paper_account_summary
    from app.services.quality_service import (
        generate_daily_report,
        get_or_create_risk_rule,
        quality_dashboard,
        risk_rule_to_dict,
        update_signal_performance,
    )
    from app.services.signal_service import generate_signals_for_wallet

    init_db()
    db = SessionLocal()
    try:
        wallet = Wallet(
            address="0x00000000000000000000000000000000feed0001",
            platform="hyperliquid",
            name="Full Verify Wallet",
            tags="verify",
            manual_score=80,
            status="active",
            notes="synthetic verification wallet",
        )
        db.add(wallet)
        db.commit()
        db.refresh(wallet)

        metric = WalletMetric(
            wallet_id=wallet.id,
            total_trades=60,
            trades_7d=12,
            trades_30d=42,
            realized_pnl=1200,
            unrealized_pnl=0,
            win_rate=61,
            profit_factor=1.8,
            avg_win=80,
            avg_loss=-35,
            max_loss=-120,
        )
        db.add(metric)
        db.commit()

        prices = {"BTC": "65000"}
        _snapshot(db, wallet.id, [])
        open_snapshot = _snapshot(db, wallet.id, [_position("BTC", "long", 1, 65000, 65000, 5)])
        open_signals = generate_signals_for_wallet(db, wallet, prices)
        duplicate_open = generate_signals_for_wallet(db, wallet, prices)

        _snapshot(db, wallet.id, [_position("BTC", "long", 1.5, 65000, 97500, 5)])
        add_signals = generate_signals_for_wallet(db, wallet, prices)

        _snapshot(db, wallet.id, [_position("BTC", "long", 0.75, 65000, 48750, 5)])
        reduce_signals = generate_signals_for_wallet(db, wallet, prices)

        _snapshot(db, wallet.id, [])
        close_signals = generate_signals_for_wallet(db, wallet, prices)

        assert len(open_signals) == 1, open_signals
        assert len(duplicate_open) == 0, duplicate_open
        assert len(add_signals) == 1, add_signals
        assert len(reduce_signals) == 1, reduce_signals
        assert len(close_signals) == 1, close_signals

        trade = add_signal_to_paper(db, open_signals[0])
        assert trade.status == "open", trade.status
        assert trade.size_usd <= 50, trade.size_usd
        assert trade.leverage <= 3, trade.leverage

        closed_count = close_from_signal(db, close_signals[0])
        assert closed_count == 1, closed_count

        summary = paper_account_summary(db)
        assert summary["open_positions"] == 0, summary
        assert summary["closed_trades"] == 1, summary

        updated = update_signal_performance(db, {"BTC": "66000"})
        assert updated >= 1, updated
        quality = quality_dashboard(db)
        assert "wallet_rankings" in quality and "signal_type_analysis" in quality, quality
        report = generate_daily_report(db, send_telegram=False)
        assert report.signal_count >= 1, report.signal_count
        rule = get_or_create_risk_rule(db)
        rule.blacklist_symbols = json.dumps(["DOGE"])
        db.commit()
        risk = risk_rule_to_dict(rule)
        assert risk["blacklist_symbols"] == ["DOGE"], risk

        discovery_service.HyperliquidApiClient = _FakeHyperliquidClient
        discovered = upsert_candidates(db, {"0x0000000000000000000000000000000000000000": "verify"})
        assert discovered == 1, discovered
        evaluated_candidates = evaluate_candidates(db, limit=1)
        assert evaluated_candidates == 1, evaluated_candidates
        discovery = discovery_summary(db)
        assert discovery["total_candidates"] >= 1, discovery
        auto_added = auto_add_recommended_candidates(db)

        result = {
            "ok": True,
            "snapshot_id": open_snapshot.id,
            "signals": db.query(Signal).count(),
            "paper_trades": db.query(PaperTrade).count(),
            "performance_updated": updated,
            "daily_report": report.report_date,
            "discovery_candidates": discovery["total_candidates"],
            "discovery_auto_added": auto_added,
            "live_test_recommendation": quality["live_test_recommendation"],
            "summary": {
                "equity": summary["current_equity"],
                "closed_trades": summary["closed_trades"],
                "open_positions": summary["open_positions"],
            },
        }
        print(json.dumps(result, ensure_ascii=False))
    finally:
        db.close()


def _snapshot(db, wallet_id, positions):
    from app.models.market_data import WalletPositionSnapshot

    snapshot = WalletPositionSnapshot(
        wallet_id=wallet_id,
        raw_json=json.dumps({"assetPositions": []}),
        positions_json=json.dumps(positions),
        account_value=100000,
        unrealized_pnl=sum(position.get("unrealized_pnl", 0) for position in positions),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def _position(coin, side, size, entry_price, position_value, leverage):
    signed_size = size if side == "long" else -size
    return {
        "coin": coin,
        "side": side,
        "size": size,
        "signed_size": signed_size,
        "entry_price": entry_price,
        "position_value": position_value,
        "unrealized_pnl": 0,
        "leverage": leverage,
    }


class _FakeHyperliquidClient:
    def __init__(self, db):
        self.db = db

    def get_user_fills(self, address):
        return [
            {"coin": "BTC", "closedPnl": "220", "time": 1_800_000_000_000},
            {"coin": "ETH", "closedPnl": "-40", "time": 1_799_999_940_000},
            {"coin": "BTC", "closedPnl": "85", "time": 1_799_999_880_000},
        ]

    def get_user_fills_by_time(self, address, start_time, end_time):
        now_ms = end_time
        return [
            {"coin": "BTC", "closedPnl": "220", "time": now_ms - 60_000},
            {"coin": "ETH", "closedPnl": "-40", "time": now_ms - 120_000},
            {"coin": "BTC", "closedPnl": "85", "time": now_ms - 180_000},
        ]

    def get_clearinghouse_state(self, address):
        return {
            "marginSummary": {"accountValue": "2000"},
            "assetPositions": [
                {"position": {"coin": "BTC", "unrealizedPnl": "30"}},
            ],
        }

    def get_open_orders(self, address):
        return []


if __name__ == "__main__":
    main()
