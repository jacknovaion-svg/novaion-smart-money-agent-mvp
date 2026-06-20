import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main() -> None:
    db_path = ROOT / "data" / "novaion_paper_trading_processor_verify.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SCHEDULER_ENABLED"] = "false"
    os.environ["PAPER_MAX_POSITION_USD"] = "50"
    os.environ["PAPER_TAKER_FEE_RATE"] = "0.0005"
    os.environ["PAPER_SLIPPAGE_RATE"] = "0.001"

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.core.database import SessionLocal, init_db
    from app.models.signal import PaperTrade, Signal
    from app.models.wallet import Wallet
    from app.services.paper_trading_processor import (
        generate_historical_dry_run_report,
        process_new_signals_for_paper_trading,
        update_open_paper_trades,
    )

    init_db()
    db = SessionLocal()
    tests = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        tests.append({"name": name, "passed": bool(condition), "detail": detail})

    try:
        cutover = datetime.now(timezone.utc)
        before = cutover - timedelta(minutes=5)
        after = cutover + timedelta(minutes=5)
        wallet = _wallet(db, "0x0000000000000000000000000000000000000001", "Paper Verify 1")
        other_wallet = _wallet(db, "0x0000000000000000000000000000000000000002", "Paper Verify 2")

        historical = _signal(db, wallet.id, "BTC", "open", "long", 100, after=before)
        dry = generate_historical_dry_run_report(db, cutover_at=cutover, output_path=ROOT / "data" / "paper_dry_run_verify.md")
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        db.refresh(historical)
        check("cutover before signal not processed", historical.status == "new" and dry["historical_new_signals"] == 1)

        open_signal = _signal(db, wallet.id, "BTC", "open", "long", 100, after=after)
        result = process_new_signals_for_paper_trading(db, cutover_at=cutover)
        trade = _open_trade(db, wallet.id, "BTC", "long")
        check("open creates paper trade", result["paper_opened"] == 1 and trade is not None and open_signal.status == "simulated")
        original_entry = trade.entry_price

        duplicate_open = _signal(db, wallet.id, "BTC", "open", "long", 101, after=after + timedelta(seconds=1))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        check(
            "duplicate open skipped",
            duplicate_open.status == "ignored"
            and db.query(PaperTrade).filter(PaperTrade.wallet_id == wallet.id, PaperTrade.symbol == "BTC").count() == 1,
        )

        add_signal = _signal(db, wallet.id, "BTC", "add", "long", 120, size=10, after=after + timedelta(seconds=2))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        db.refresh(trade)
        expected_weighted = round(((original_entry * 20) + (120 * 1.001 * 10)) / 30, 8)
        check("add increases position", add_signal.status == "simulated" and round(trade.size_usd, 6) == 30)
        check("add weighted average entry", round(trade.entry_price, 8) == expected_weighted)

        orphan_add = _signal(db, wallet.id, "ETH", "add", "long", 2000, after=after + timedelta(seconds=3))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        check("orphan add skipped", orphan_add.status == "ignored" and _open_trade(db, wallet.id, "ETH", "long") is None)

        reduce_signal = _signal(db, wallet.id, "BTC", "reduce", "long", 130, after=after + timedelta(seconds=4))
        size_before_reduce = trade.size_usd
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        db.refresh(trade)
        check("reduce cuts 50 percent", reduce_signal.status == "simulated" and round(trade.size_usd, 6) == round(size_before_reduce * 0.5, 6))
        check("reduce realizes pnl", trade.pnl > 0 and trade.fees > 0 and trade.slippage_adjustment != 0)

        orphan_reduce = _signal(db, wallet.id, "ETH", "reduce", "long", 2000, after=after + timedelta(seconds=5))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        check("orphan reduce skipped", orphan_reduce.status == "ignored")

        other_open = _signal(db, other_wallet.id, "BTC", "open", "long", 100, after=after + timedelta(seconds=6))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        other_trade = _open_trade(db, other_wallet.id, "BTC", "long")
        close_signal = _signal(db, wallet.id, "BTC", "close", "close", 125, after=after + timedelta(seconds=7))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        db.refresh(trade)
        db.refresh(other_trade)
        check("close only matching wallet symbol", close_signal.status == "simulated" and trade.status == "closed" and other_trade.status == "open")

        amb_wallet = _wallet(db, "0x0000000000000000000000000000000000000003", "Ambiguous")
        _signal(db, amb_wallet.id, "SOL", "open", "long", 100, after=after + timedelta(seconds=8))
        _signal(db, amb_wallet.id, "SOL", "open", "short", 100, after=after + timedelta(seconds=9))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        ambiguous_close = _signal(db, amb_wallet.id, "SOL", "close", "close", 100, after=after + timedelta(seconds=10))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        check("ambiguous close skipped", ambiguous_close.status == "ignored")

        high_risk = _signal(db, wallet.id, "DOGE", "open", "long", 0.1, risk=90, after=after + timedelta(seconds=11))
        zero_size = _signal(db, wallet.id, "DOGE", "open", "long", 0.1, size=0, after=after + timedelta(seconds=12))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        check("high risk skipped", high_risk.status == "ignored")
        check("zero size skipped", zero_size.status == "ignored")

        idempotent_signal = _signal(db, wallet.id, "ARB", "open", "long", 2, after=after + timedelta(seconds=13))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        trade_count_after_first = db.query(PaperTrade).count()
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        check("processor is idempotent", idempotent_signal.status == "simulated" and db.query(PaperTrade).count() == trade_count_after_first)

        arb_trade = _open_trade(db, wallet.id, "ARB", "long")
        old_mark = arb_trade.mark_price
        update_open_paper_trades(db, {"ARB": "2.5"})
        db.refresh(arb_trade)
        check("mark price updates unrealized pnl", arb_trade.mark_price == 2.5 and arb_trade.unrealized_pnl > 0)
        update_open_paper_trades(db, {"ARB": "0"})
        db.refresh(arb_trade)
        check("missing price does not overwrite with zero", arb_trade.mark_price == 2.5 and old_mark != 0)

        long_wallet = _wallet(db, "0x0000000000000000000000000000000000000004", "Long Short")
        long_signal = _signal(db, long_wallet.id, "XRP", "open", "long", 1, after=after + timedelta(seconds=14))
        short_signal = _signal(db, long_wallet.id, "LTC", "open", "short", 100, after=after + timedelta(seconds=15))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        xrp_trade = _open_trade(db, long_wallet.id, "XRP", "long")
        ltc_trade = _open_trade(db, long_wallet.id, "LTC", "short")
        update_open_paper_trades(db, {"XRP": "1.2", "LTC": "80"})
        db.refresh(xrp_trade)
        db.refresh(ltc_trade)
        check("long pnl direction positive on price up", xrp_trade.unrealized_pnl > 0 and long_signal.status == "simulated")
        check("short pnl direction positive on price down", ltc_trade.unrealized_pnl > 0 and short_signal.status == "simulated")
        close_fee_signal = _signal(db, long_wallet.id, "XRP", "close", "long", 1.2, after=after + timedelta(seconds=16))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        db.refresh(xrp_trade)
        check("fees and slippage included", close_fee_signal.status == "simulated" and xrp_trade.fees > 0 and xrp_trade.slippage_adjustment != 0)

        passed = len([item for item in tests if item["passed"]])
        output = {
            "tests_total": len(tests),
            "tests_passed": passed,
            "tests_failed": len(tests) - passed,
            "failed": [item for item in tests if not item["passed"]],
            "signals_total": db.query(Signal).count(),
            "paper_trades_total": db.query(PaperTrade).count(),
            "open_paper_trades": db.query(PaperTrade).filter(PaperTrade.status == "open").count(),
            "closed_paper_trades": db.query(PaperTrade).filter(PaperTrade.status == "closed").count(),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        raise SystemExit(0 if output["tests_failed"] == 0 else 1)
    finally:
        db.close()


def _wallet(db, address: str, name: str):
    from app.models.wallet import Wallet

    wallet = Wallet(address=address, platform="hyperliquid", name=name, tags="", manual_score=80, status="active")
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    return wallet


def _signal(
    db,
    wallet_id: int,
    symbol: str,
    signal_type: str,
    side: str,
    price: float,
    *,
    size: float = 20,
    risk: int = 50,
    after: datetime,
):
    from app.models.signal import Signal

    signal = Signal(
        wallet_id=wallet_id,
        platform="hyperliquid",
        symbol=symbol,
        signal_type=signal_type,
        side=side,
        source_size=size,
        source_leverage=2,
        source_entry_price=price,
        current_price=price,
        confidence_score=80,
        risk_score=risk,
        suggested_size_usd=size,
        reason="processor verification",
        status="new",
        source_trade_id=f"verify-{wallet_id}-{symbol}-{signal_type}-{side}-{after.timestamp()}",
        dedupe_key=f"verify-{wallet_id}-{symbol}-{signal_type}-{side}-{after.timestamp()}",
        created_at=after,
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


def _open_trade(db, wallet_id: int, symbol: str, side: str):
    from app.models.signal import PaperTrade

    return (
        db.query(PaperTrade)
        .filter(PaperTrade.wallet_id == wallet_id, PaperTrade.symbol == symbol, PaperTrade.side == side, PaperTrade.status == "open")
        .first()
    )


if __name__ == "__main__":
    main()
