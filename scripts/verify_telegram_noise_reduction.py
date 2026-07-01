import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main() -> None:
    db_path = ROOT / "data" / "novaion_telegram_noise_verify.db"
    for path in (db_path, db_path.with_suffix(".db-wal"), db_path.with_suffix(".db-shm")):
        if path.exists():
            path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SCHEDULER_ENABLED"] = "false"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
    os.environ["TELEGRAM_CHAT_ID"] = "test-chat"
    os.environ["SMART_MONEY_TELEGRAM_BOSS_MODE"] = "true"
    os.environ["SMART_MONEY_TELEGRAM_AGGREGATION_MINUTES"] = "30"
    os.environ["PAPER_ACCOUNT_STARTING_BALANCE_USD"] = "100"

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.core.database import SessionLocal, init_db
    from app.models.signal import DailyReport, PaperTrade, Signal
    from app.models.system_log import SystemLog
    from app.models.wallet import Wallet
    from app.services import telegram_service
    from app.services.system_log_service import write_log
    from app.services.telegram_service import (
        flush_signal_aggregation_notifications,
        send_daily_report_notification,
        send_signal_notification,
    )

    init_db()
    db = SessionLocal()
    sent_messages = []
    tests = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(_url, json=None, timeout=None):
        sent_messages.append(json["text"])
        return FakeResponse()

    telegram_service.httpx.post = fake_post

    def check(name: str, condition: bool, detail: str = "") -> None:
        tests.append({"name": name, "passed": bool(condition), "detail": detail})

    try:
        now = datetime.now(timezone.utc)
        wallet = _wallet(db, "0x844600000000000000000000000000000000ba1b", "Noise Wallet")

        open_signal = _signal(db, wallet.id, "ZRO", "open", "long", 50000, 0.90419, now)
        send_signal_notification(db, open_signal, wallet)
        check("open sends one simplified message", len(sent_messages) == 1 and "【聪明钱新开仓】" in sent_messages[-1])
        check("open hides technical fields", _no_tech_fields(sent_messages[-1]))
        check("open separates source and simulation", "源钱包动作：" in sent_messages[-1] and "系统模拟动作：" in sent_messages[-1])
        check("open shortens wallet", "0x8446...ba1b" in sent_messages[-1] and wallet.address not in sent_messages[-1])

        add_1 = _signal(db, wallet.id, "BTC", "add", "short", 345.65, 59000, now)
        add_2 = _signal(db, wallet.id, "BTC", "add", "short", 649.04, 59100, now + timedelta(seconds=1))
        before = len(sent_messages)
        send_signal_notification(db, add_1, wallet)
        send_signal_notification(db, add_2, wallet)
        check("add does not send immediately", len(sent_messages) == before)
        add_1.created_at = now - timedelta(minutes=35)
        add_2.created_at = now - timedelta(minutes=34)
        db.commit()
        write_log(
            db,
            level="info",
            module="paper_trading",
            message="insufficient_paper_funds",
            payload={"signal_id": add_1.id, "wallet_id": wallet.id, "symbol": "BTC", "paper_trade_id": 10},
        )
        sent_count = flush_signal_aggregation_notifications(db, now=now)
        db.refresh(add_1)
        db.refresh(add_2)
        check("add aggregation sends one summary", sent_count == 1 and len(sent_messages) == before + 1)
        check("add aggregation marks included signals", add_1.telegram_sent_at is not None and add_2.telegram_sent_at is not None)
        check("add aggregation shows funds block", "因模拟资金不足，未继续加仓" in sent_messages[-1])
        check("add aggregation hides technical fields", _no_tech_fields(sent_messages[-1]))

        reduce_1 = _signal(db, wallet.id, "BTC", "reduce", "short", 649.04, 59200, now - timedelta(minutes=33))
        reduce_2 = _signal(db, wallet.id, "BTC", "reduce", "short", 345.65, 59300, now - timedelta(minutes=32))
        send_signal_notification(db, reduce_1, wallet)
        send_signal_notification(db, reduce_2, wallet)
        write_log(
            db,
            level="info",
            module="paper_trading",
            message="paper_reduced",
            payload={"signal_id": reduce_1.id, "wallet_id": wallet.id, "symbol": "BTC", "paper_trade_id": 10},
        )
        before_reduce = len(sent_messages)
        sent_count = flush_signal_aggregation_notifications(db, now=now)
        check("reduce aggregation sends one summary", sent_count == 1 and len(sent_messages) == before_reduce + 1)
        check("reduce conclusion", "信心减弱" in sent_messages[-1])

        close_signal = _signal(db, wallet.id, "ZRO", "close", "close", 0, 0.91, now + timedelta(seconds=1))
        write_log(
            db,
            level="info",
            module="paper_trading",
            message="paper_closed",
            payload={"signal_id": close_signal.id, "wallet_id": wallet.id, "symbol": "ZRO", "realized_pnl": -0.37},
        )
        send_signal_notification(db, close_signal, wallet)
        check("close sends immediately", "【聪明钱已平仓】" in sent_messages[-1] and "净亏损 $0.37" in sent_messages[-1])

        previous_long = _signal(db, wallet.id, "ETH", "open", "long", 1000, 1600, now + timedelta(seconds=2))
        previous_long.telegram_sent_at = now
        db.commit()
        reversal = _signal(db, wallet.id, "ETH", "open", "short", 1200, 1590, now + timedelta(seconds=3))
        send_signal_notification(db, reversal, wallet)
        check("reversal sends priority message", "【重点提醒｜方向反转】" in sent_messages[-1] and "原方向：做多" in sent_messages[-1] and "新方向：做空" in sent_messages[-1])

        ignored_signal = _signal(db, wallet.id, "SOL", "add", "long", 200, 75, now)
        write_log(db, level="info", module="paper_trading", message="orphan_add", payload={"signal_id": ignored_signal.id})
        write_log(db, level="info", module="paper_trading", message="missing_data", payload={"signal_id": ignored_signal.id})
        db.add(PaperTrade(signal_id=open_signal.id, wallet_id=wallet.id, symbol="ZRO", side="long", entry_price=1, size_usd=20, leverage=3, status="open", unrealized_pnl=1.5))
        report = DailyReport(
            report_date=now.date().isoformat(),
            signal_count=8,
            simulated_pnl=-4.44,
            best_wallet="0x8446...ba1b",
            worst_wallet="0x86dd...f065",
        )
        db.add(report)
        db.commit()
        before_daily = len(sent_messages)
        send_daily_report_notification(db, report)
        check("daily sends one boss summary", len(sent_messages) == before_daily + 1 and "【NOVAION｜每日汇总｜非真实交易】" in sent_messages[-1])
        check("daily has ignored buckets", "资金不足：" in sent_messages[-1] and "无对应模拟仓位：" in sent_messages[-1] and "数据缺失：" in sent_messages[-1])
        check("daily avoids fake win rate numbers", "胜率：" not in sent_messages[-1] and "胜率 0" not in sent_messages[-1])

        def failing_post(_url, json=None, timeout=None):
            raise RuntimeError("telegram down")

        telegram_service.httpx.post = failing_post
        fail_signal = _signal(db, wallet.id, "ARB", "open", "long", 100, 2, now + timedelta(seconds=4))
        before_fail_status = fail_signal.status
        result = send_signal_notification(db, fail_signal, wallet)
        db.refresh(fail_signal)
        fail_log = db.query(SystemLog).filter(SystemLog.message == "Signal notification failed").first()
        check("telegram failure isolated", result is False and fail_signal.status == before_fail_status and fail_log is not None)

        passed = len([item for item in tests if item["passed"]])
        output = {
            "tests_total": len(tests),
            "tests_passed": passed,
            "tests_failed": len(tests) - passed,
            "failed": [item for item in tests if not item["passed"]],
            "samples": {
                "open": sent_messages[0],
                "aggregation": sent_messages[1],
                "close": [message for message in sent_messages if "聪明钱已平仓" in message][-1],
                "reversal": [message for message in sent_messages if "方向反转" in message][-1],
                "daily": sent_messages[-1],
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        raise SystemExit(0 if output["tests_failed"] == 0 else 1)
    finally:
        db.close()


def _wallet(db, address: str, name: str):
    from app.models.wallet import Wallet

    wallet = Wallet(address=address, platform="hyperliquid", name=name, tags="manual-approved", manual_score=80, status="active")
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    return wallet


def _signal(db, wallet_id: int, symbol: str, signal_type: str, side: str, source_size: float, price: float, created_at: datetime):
    from app.models.signal import Signal

    signal = Signal(
        wallet_id=wallet_id,
        platform="hyperliquid",
        symbol=symbol,
        signal_type=signal_type,
        side=side,
        source_size=source_size,
        source_leverage=3,
        source_entry_price=price,
        current_price=price,
        confidence_score=80,
        risk_score=40,
        suggested_action="Only simulate. Do not live trade.",
        suggested_size_usd=20,
        reason="Wallet score 80, 30D win rate 60%, profit factor 1.4.",
        status="new",
        source_trade_id=f"noise-{wallet_id}-{symbol}-{signal_type}-{side}-{created_at.timestamp()}",
        dedupe_key=f"noise-{wallet_id}-{symbol}-{signal_type}-{side}-{created_at.timestamp()}",
        created_at=created_at,
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


def _no_tech_fields(message: str) -> bool:
    blocked = [
        "signal_id",
        "paper_trade_id",
        "auto-discovered",
        "manual-approved",
        "Only simulate",
        "profit factor",
        "heartbeat",
        "Scheduler",
    ]
    return not any(item in message for item in blocked)


if __name__ == "__main__":
    main()
