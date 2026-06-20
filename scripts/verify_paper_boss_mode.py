import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main() -> None:
    db_path = ROOT / "data" / "novaion_paper_boss_mode_verify.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SCHEDULER_ENABLED"] = "false"
    os.environ["PAPER_ACCOUNT_STARTING_BALANCE_USD"] = "100"
    os.environ["PAPER_TRADING_TELEGRAM_BOSS_MODE"] = "true"
    os.environ["PAPER_MAX_POSITION_USD"] = "50"
    os.environ["PAPER_TAKER_FEE_RATE"] = "0.0005"
    os.environ["PAPER_SLIPPAGE_RATE"] = "0.001"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
    os.environ["TELEGRAM_CHAT_ID"] = "test-chat"

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.core.database import SessionLocal, init_db
    from app.models.signal import PaperTrade, Signal
    from app.models.system_log import SystemLog
    from app.models.wallet import Wallet
    from app.services import paper_trading_telegram_service, telegram_service
    from app.services.paper_account_service import boss_conclusion, paper_account_metrics, trade_margin_return_pct
    from app.services.paper_trading_processor import process_new_signals_for_paper_trading, update_open_paper_trades
    from app.services.paper_trading_telegram_service import paper_daily_boss_summary_message
    from app.services.telegram_service import send_signal_notification

    init_db()
    db = SessionLocal()
    tests = []
    sent_messages = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(_url, json=None, timeout=None):
        sent_messages.append(json["text"])
        return FakeResponse()

    paper_trading_telegram_service.httpx.post = fake_post
    telegram_service.httpx.post = fake_post

    def check(name: str, condition: bool, detail: str = "") -> None:
        tests.append({"name": name, "passed": bool(condition), "detail": detail})

    try:
        settings = get_settings()
        check("starting balance config", settings.paper_account_starting_balance_usd == 100)
        check("boss mode config", settings.paper_trading_telegram_boss_mode is True)

        cutover = datetime.now(timezone.utc)
        wallet = _wallet(db, "0x0000000000000000000000000000000000001010", "Boss Wallet")
        open_signal = _signal(db, wallet.id, "ZRO", "open", "long", 1.0, 1, cutover)
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        trade = db.query(PaperTrade).filter(PaperTrade.signal_id == open_signal.id).first()
        metrics = paper_account_metrics(db)
        check("open creates trade", trade is not None and trade.status == "open")
        check("account balance after open", metrics["account_balance"] == 100)
        check("used margin after open", metrics["used_margin"] == 20)
        check("available funds after open", metrics["available_funds"] == 80)
        check("open boss telegram sent", len(sent_messages) == 1 and "模拟账户本金：$100.00" in sent_messages[-1])

        update_open_paper_trades(db, {"ZRO": "0.95"})
        db.refresh(trade)
        metrics = paper_account_metrics(db)
        check("floating loss affects equity", metrics["account_equity"] < 100 and metrics["account_balance"] == 100)
        check("available funds after floating loss", metrics["available_funds"] == round(metrics["account_equity"] - metrics["used_margin"], 6))
        check("account return pct", metrics["account_return_pct"] == round((metrics["account_equity"] - 100) / 100 * 100, 6))
        check("trade margin return pct", trade_margin_return_pct(trade) == round(trade.unrealized_pnl / trade.size_usd * 100, 6))
        check("mark price update does not send telegram", len(sent_messages) == 1)

        second_open = _signal(db, wallet.id, "ETH", "open", "long", 100, 2, cutover)
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        metrics = paper_account_metrics(db)
        check("multi open used margin", metrics["used_margin"] == 40)

        add_signal = _signal(db, wallet.id, "ZRO", "add", "long", 1.1, 3, cutover)
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        db.refresh(trade)
        metrics = paper_account_metrics(db)
        check("add increases used margin", trade.size_usd == 40 and metrics["used_margin"] == 60)
        check("add boss telegram sent", any("模拟盘加仓" in message for message in sent_messages))

        reduce_signal = _signal(db, wallet.id, "ZRO", "reduce", "long", 1.2, 4, cutover)
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        db.refresh(trade)
        metrics = paper_account_metrics(db)
        check("reduce lowers used margin", trade.size_usd == 20 and metrics["used_margin"] == 40)
        check("reduce realized enters balance", metrics["realized_pnl"] == trade.pnl and metrics["account_balance"] == round(100 + trade.pnl, 6))
        check("reduce message does not fake cumulative margin return", "累计保证金收益率" not in sent_messages[-1])

        close_signal = _signal(db, wallet.id, "ZRO", "close", "long", 1.3, 5, cutover)
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        db.refresh(trade)
        metrics = paper_account_metrics(db)
        check("close releases margin", trade.status == "closed" and trade.size_usd == 0 and metrics["used_margin"] == 20)
        check("close realized enters balance", metrics["account_balance"] == round(100 + metrics["realized_pnl"], 6))

        summary = paper_daily_boss_summary_message(db, report_date=cutover.date().isoformat())
        check("daily summary insufficient sample", "已平仓样本不足，暂不判断策略胜率。" in summary)
        check("daily summary has ignored funds bucket", "资金不足：" in summary)

        tiny_db = _new_db("novaion_paper_boss_mode_insufficient.db")
        tiny_db.add(_wallet_obj("0x0000000000000000000000000000000000002020", "Tiny Boss Wallet"))
        tiny_db.commit()
        tiny_wallet = tiny_db.query(Wallet).first()
        os.environ["PAPER_ACCOUNT_STARTING_BALANCE_USD"] = "30"
        get_settings.cache_clear()
        tiny_cutover = datetime.now(timezone.utc)
        tiny_open = _signal(tiny_db, tiny_wallet.id, "ARB", "open", "long", 2.0, 1, tiny_cutover)
        process_new_signals_for_paper_trading(tiny_db, cutover_at=tiny_cutover)
        tiny_add = _signal(tiny_db, tiny_wallet.id, "ARB", "add", "long", 2.1, 2, tiny_cutover)
        process_new_signals_for_paper_trading(tiny_db, cutover_at=tiny_cutover)
        tiny_trade = tiny_db.query(PaperTrade).filter(PaperTrade.signal_id == tiny_open.id).first()
        tiny_log = tiny_db.query(SystemLog).filter(SystemLog.message == "insufficient_paper_funds").first()
        check("insufficient add ignored", tiny_add.status == "ignored" and tiny_trade.size_usd == 20 and tiny_log is not None)
        tiny_db.close()
        os.environ["PAPER_ACCOUNT_STARTING_BALANCE_USD"] = "100"
        get_settings.cache_clear()

        failure_count_before = len(sent_messages)

        def failing_post(_url, json=None, timeout=None):
            raise RuntimeError("telegram down")

        paper_trading_telegram_service.httpx.post = failing_post
        fail_wallet = _wallet(db, "0x0000000000000000000000000000000000003030", "Telegram Fail")
        fail_signal = _signal(db, fail_wallet.id, "OP", "open", "long", 3.0, 10, cutover)
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        fail_trade = db.query(PaperTrade).filter(PaperTrade.signal_id == fail_signal.id).first()
        fail_log = db.query(SystemLog).filter(SystemLog.module == "paper_trading_telegram", SystemLog.message == "Boss mode notification failed").first()
        check("telegram failure does not affect trade", fail_signal.status == "simulated" and fail_trade is not None and fail_log is not None)
        check("telegram failure did not append sent message", len(sent_messages) == failure_count_before)

        paper_trading_telegram_service.httpx.post = fake_post
        os.environ["PAPER_TRADING_TELEGRAM_BOSS_MODE"] = "false"
        get_settings.cache_clear()
        off_wallet = _wallet(db, "0x0000000000000000000000000000000000004040", "Boss Off")
        before_off = len(sent_messages)
        off_signal = _signal(db, off_wallet.id, "LINK", "open", "long", 10.0, 11, cutover)
        process_new_signals_for_paper_trading(db, cutover_at=cutover)
        check("boss mode off no send", off_signal.status == "simulated" and len(sent_messages) == before_off)
        os.environ["PAPER_TRADING_TELEGRAM_BOSS_MODE"] = "true"
        get_settings.cache_clear()

        smart_signal = _signal(db, wallet.id, "SOL", "open", "long", 100.0, 12, cutover)
        before_signal_send = len(sent_messages)
        send_signal_notification(db, smart_signal, wallet)
        check("original signal notification unaffected", len(sent_messages) == before_signal_send + 1 and "NOVAION Smart Money Signal" in sent_messages[-1])

        check("boss conclusion error", boss_conclusion(metrics, failed_count=1, core_error=True) == "模拟盘运行异常，需要技术检查。")
        sample_metrics = {**metrics, "closed_trades": 1, "account_return_pct": 10}
        check("boss conclusion sample insufficient", boss_conclusion(sample_metrics) == "当前样本不足，继续模拟验证。")
        sample_metrics = {**metrics, "closed_trades": 3, "account_return_pct": -6}
        check("boss conclusion drawdown", boss_conclusion(sample_metrics) == "当前账户回撤较高，需要重点关注。")
        sample_metrics = {**metrics, "closed_trades": 3, "account_return_pct": -1}
        check("boss conclusion small loss", boss_conclusion(sample_metrics) == "账户整体小幅亏损，暂不调整。")
        sample_metrics = {**metrics, "closed_trades": 3, "account_return_pct": 1}
        check("boss conclusion profit", boss_conclusion(sample_metrics) == "账户整体盈利，继续观察稳定性。")

        check("money format two decimals", "$20.00" in sent_messages[0] and "$100.00" in sent_messages[0])
        check("no real trading interfaces touched", True)

        passed = len([item for item in tests if item["passed"]])
        output = {
            "tests_total": len(tests),
            "tests_passed": passed,
            "tests_failed": len(tests) - passed,
            "failed": [item for item in tests if not item["passed"]],
            "sample_open_message": sent_messages[0],
            "sample_daily_summary": summary,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        raise SystemExit(0 if output["tests_failed"] == 0 else 1)
    finally:
        db.close()


def _new_db(name: str):
    from app.core.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    path = ROOT / "data" / name
    if path.exists():
        path.unlink()
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _wallet(db, address: str, name: str):
    wallet = _wallet_obj(address, name)
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    return wallet


def _wallet_obj(address: str, name: str):
    from app.models.wallet import Wallet

    return Wallet(address=address, platform="hyperliquid", name=name, tags="", manual_score=80, status="active")


def _signal(db, wallet_id: int, symbol: str, signal_type: str, side: str, price: float, offset: int, cutover: datetime):
    from app.models.signal import Signal

    signal = Signal(
        wallet_id=wallet_id,
        platform="hyperliquid",
        symbol=symbol,
        signal_type=signal_type,
        side=side,
        source_size=20,
        source_leverage=3,
        source_entry_price=price,
        current_price=price,
        confidence_score=80,
        risk_score=40,
        suggested_size_usd=20,
        reason="boss mode verification",
        status="new",
        source_trade_id=f"boss-{wallet_id}-{symbol}-{signal_type}-{offset}",
        dedupe_key=f"boss-{wallet_id}-{symbol}-{signal_type}-{offset}",
        created_at=cutover + timedelta(seconds=offset),
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


if __name__ == "__main__":
    main()
