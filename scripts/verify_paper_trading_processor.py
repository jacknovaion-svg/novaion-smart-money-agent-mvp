import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import event


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main() -> None:
    db_path = ROOT / "data" / "novaion_paper_trading_processor_verify.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SCHEDULER_ENABLED"] = "false"
    os.environ["PAPER_ACCOUNT_STARTING_BALANCE_USD"] = "2000"
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

        direct = _run_sequence(db, cutover, "Direct Close", [("open", "long", 100), ("close", "long", 110)])
        check("direct close net pnl is single close result", direct["trade"]["status"] == "closed" and direct["trade"]["pnl"] == direct["sum"]["net_pnl"])
        check("direct close zeroes remaining size", direct["trade"]["size_usd"] == 0)

        one_reduce = _run_sequence(db, cutover, "One Reduce Close", [("open", "long", 100), ("reduce", "long", 110), ("close", "long", 120)])
        check("one reduce then close cumulative pnl", _fields_match_sum(one_reduce))

        two_reduce = _run_sequence(
            db,
            cutover,
            "Two Reduce Close",
            [("open", "long", 100), ("reduce", "long", 110), ("reduce", "long", 120), ("close", "long", 130)],
        )
        check("two reduces then close cumulative raw pnl", two_reduce["trade"]["raw_pnl"] == two_reduce["sum"]["raw_pnl"])
        check("two reduces then close cumulative fees", two_reduce["trade"]["fees"] == two_reduce["sum"]["fees"])
        check("two reduces then close cumulative slippage", two_reduce["trade"]["slippage_adjustment"] == two_reduce["sum"]["slippage_adjustment"])
        check("two reduces then close cumulative net pnl", two_reduce["trade"]["net_pnl"] == two_reduce["sum"]["net_pnl"])
        check("two reduces then close pnl equals net pnl", two_reduce["trade"]["pnl"] == two_reduce["trade"]["net_pnl"])

        losing = _run_sequence(db, cutover, "Losing Long", [("open", "long", 100), ("reduce", "long", 90), ("close", "long", 80)])
        check("losing reduce close accumulates negative pnl", _fields_match_sum(losing) and losing["trade"]["pnl"] < 0)

        short = _run_sequence(db, cutover, "Short Close", [("open", "short", 100), ("reduce", "short", 90), ("close", "short", 80)])
        check("short reduce close cumulative pnl", _fields_match_sum(short) and short["trade"]["pnl"] > 0)

        duplicate_close = _run_sequence(db, cutover, "Duplicate Close", [("open", "long", 100), ("close", "long", 110)])
        dup_signal = duplicate_close["signals"][-1]
        dup_trade = db.get(PaperTrade, duplicate_close["trade"]["id"])
        before_duplicate = _trade_snapshot(dup_trade)
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        db.refresh(dup_trade)
        check("duplicate close processor run does not recalculate", dup_signal.status == "simulated" and _trade_snapshot(dup_trade) == before_duplicate)

        rollback_wallet = _wallet(db, "0x0000000000000000000000000000000000000005", "Rollback")
        rollback_open = _signal(db, rollback_wallet.id, "UNI", "open", "long", 100, after=after + timedelta(seconds=50))
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        rollback_trade = _open_trade(db, rollback_wallet.id, "UNI", "long")
        rollback_close = _signal(db, rollback_wallet.id, "UNI", "close", "long", 110, after=after + timedelta(seconds=51))
        fail_once = {"active": True}

        def fail_before_commit(session):
            if fail_once["active"]:
                fail_once["active"] = False
                raise RuntimeError("simulated close commit failure")

        event.listen(db, "before_commit", fail_before_commit)
        try:
            process_new_signals_for_paper_trading(db, cutover_at=cutover)
        finally:
            event.remove(db, "before_commit", fail_before_commit)
        db.expire_all()
        rollback_trade = db.get(PaperTrade, rollback_trade.id)
        rollback_close = db.get(Signal, rollback_close.id)
        check(
            "close failure rolls back partial trade update",
            rollback_close.status == "failed"
            and rollback_trade.status == "open"
            and rollback_trade.pnl == 0
            and rollback_trade.fees == 0
            and rollback_trade.size_usd == 20,
        )

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


def _run_sequence(db, cutover: datetime, name: str, steps: list[tuple[str, str, float]]):
    from app.models.signal import PaperTrade, Signal
    from app.models.wallet import Wallet
    from app.services.paper_trading_processor import process_new_signals_for_paper_trading

    index = 1000 + db.query(Wallet).count()
    wallet = _wallet(db, f"0x{index + 100:040x}", name)
    symbol = f"T{index}"
    after = cutover + timedelta(hours=1, seconds=index)
    signals = []
    increments = []
    trade = None
    previous = None
    for offset, (signal_type, side, price) in enumerate(steps):
        signal = _signal(db, wallet.id, symbol, signal_type, side, price, after=after + timedelta(seconds=offset))
        signals.append(signal)
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        trade = (
            db.query(PaperTrade)
            .filter(PaperTrade.wallet_id == wallet.id, PaperTrade.symbol == symbol)
            .order_by(PaperTrade.id.desc())
            .first()
        )
        db.refresh(signal)
        if trade:
            db.refresh(trade)
            current = _trade_snapshot(trade)
            if signal_type in {"reduce", "close"}:
                base = previous or {"raw_pnl": 0, "fees": 0, "slippage_adjustment": 0, "net_pnl": 0, "pnl": 0}
                increments.append(
                    {
                        "step": signal_type,
                        "raw_pnl": round(current["raw_pnl"] - base["raw_pnl"], 6),
                        "fees": round(current["fees"] - base["fees"], 6),
                        "slippage_adjustment": round(current["slippage_adjustment"] - base["slippage_adjustment"], 6),
                        "net_pnl": round(current["net_pnl"] - base["net_pnl"], 6),
                        "pnl": round(current["pnl"] - base["pnl"], 6),
                    }
                )
            previous = current
    totals = {
        "raw_pnl": round(sum(item["raw_pnl"] for item in increments), 6),
        "fees": round(sum(item["fees"] for item in increments), 6),
        "slippage_adjustment": round(sum(item["slippage_adjustment"] for item in increments), 6),
        "net_pnl": round(sum(item["net_pnl"] for item in increments), 6),
        "pnl": round(sum(item["pnl"] for item in increments), 6),
    }
    return {"wallet": wallet.id, "symbol": symbol, "signals": signals, "increments": increments, "sum": totals, "trade": _trade_snapshot(trade)}


def _trade_snapshot(trade):
    return {
        "id": trade.id,
        "status": trade.status,
        "size_usd": round(trade.size_usd or 0, 6),
        "raw_pnl": round(trade.raw_pnl or 0, 6),
        "fees": round(trade.fees or 0, 6),
        "slippage_adjustment": round(trade.slippage_adjustment or 0, 6),
        "net_pnl": round(trade.net_pnl or 0, 6),
        "pnl": round(trade.pnl or 0, 6),
        "unrealized_pnl": round(trade.unrealized_pnl or 0, 6),
        "unrealized_pnl_pct": round(trade.unrealized_pnl_pct or 0, 6),
    }


def _fields_match_sum(result) -> bool:
    trade = result["trade"]
    totals = result["sum"]
    return (
        trade["raw_pnl"] == totals["raw_pnl"]
        and trade["fees"] == totals["fees"]
        and trade["slippage_adjustment"] == totals["slippage_adjustment"]
        and trade["net_pnl"] == totals["net_pnl"]
        and trade["pnl"] == totals["net_pnl"]
    )


if __name__ == "__main__":
    main()
