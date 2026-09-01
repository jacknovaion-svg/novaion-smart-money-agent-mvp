from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.signal import PaperTrade, Signal
from app.models.system_log import SystemLog
from app.models.wallet import Wallet
from app.services.paper_account_service import boss_conclusion, paper_account_metrics, trade_margin_return_pct, trade_notional
from app.services.system_log_service import write_log


def send_paper_trade_boss_notification(
    db: Session,
    *,
    event_type: str,
    trade: PaperTrade,
    signal: Signal,
    event_payload: dict[str, Any] | None = None,
) -> bool:
    settings = get_settings()
    if not settings.paper_trading_telegram_boss_mode:
        write_log(
            db,
            level="info",
            module="paper_trading_telegram",
            message="Boss mode disabled; paper trade notification skipped",
            payload={"event_type": event_type, "trade_id": trade.id},
        )
        return False
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        write_log(
            db,
            level="info",
            module="paper_trading_telegram",
            message="Telegram not configured; paper trade notification skipped",
            payload={"event_type": event_type, "trade_id": trade.id},
        )
        return False

    try:
        text = paper_trade_boss_message(db, event_type=event_type, trade=trade, signal=signal, event_payload=event_payload or {})
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="paper_trading_telegram",
            message="Boss mode message build failed",
            payload={"event_type": event_type, "trade_id": trade.id, "error": str(exc)},
        )
        return False
    return _send_text(db, text, {"event_type": event_type, "trade_id": trade.id, "symbol": trade.symbol})


def send_paper_daily_boss_summary(db: Session, report_date: str | None = None) -> bool:
    settings = get_settings()
    if not settings.paper_trading_telegram_boss_mode:
        write_log(db, level="info", module="paper_trading_telegram", message="Boss mode disabled; daily summary skipped")
        return False
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        write_log(db, level="info", module="paper_trading_telegram", message="Telegram not configured; daily summary skipped")
        return False
    text = paper_daily_boss_summary_message(db, report_date=report_date)
    return _send_text(db, text, {"report_date": report_date or datetime.now(timezone.utc).date().isoformat()})


def paper_trade_boss_message(
    db: Session,
    *,
    event_type: str,
    trade: PaperTrade,
    signal: Signal,
    event_payload: dict[str, Any] | None = None,
) -> str:
    event_payload = event_payload or {}
    metrics = paper_account_metrics(db)
    wallet = db.get(Wallet, trade.wallet_id)
    title = _trade_title(trade)
    if event_type == "open":
        return _open_message(title, trade, signal, wallet, metrics)
    if event_type == "add":
        return _add_message(title, trade, wallet, metrics, event_payload)
    if event_type == "reduce":
        return _reduce_message(title, trade, wallet, metrics, event_payload)
    if event_type == "close":
        return _close_message(title, trade, wallet, metrics)
    return "\n".join(["【NOVAION｜模拟盘｜非真实交易】", "", title, "", "老板结论：", "当前样本不足，继续模拟验证。"])


def paper_daily_boss_summary_message(db: Session, report_date: str | None = None) -> str:
    day = report_date or datetime.now(timezone.utc).date().isoformat()
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    metrics = paper_account_metrics(db)
    signals = db.query(Signal).filter(Signal.created_at >= start, Signal.created_at < end).all()
    logs = db.query(SystemLog).filter(SystemLog.module == "paper_trading", SystemLog.created_at >= start, SystemLog.created_at < end).all()
    opened = _count_logs(logs, "paper_opened")
    added = _count_logs(logs, "paper_added")
    reduced = _count_logs(logs, "paper_reduced")
    closed = _count_logs(logs, "paper_closed")
    ignored = {
        "high_risk": _count_logs(logs, "high_risk"),
        "orphan": _count_logs(logs, "orphan_add") + _count_logs(logs, "orphan_reduce") + _count_logs(logs, "orphan_close"),
        "insufficient": _count_logs(logs, "insufficient_paper_funds"),
        "missing_data": _count_logs(logs, "missing_data"),
    }
    closed_today = db.query(PaperTrade).filter(PaperTrade.closed_at >= start, PaperTrade.closed_at < end).all()
    today_realized = round(sum(trade.pnl or 0 for trade in closed_today), 6)
    sample_line = "已平仓样本不足，暂不判断策略胜率。" if metrics["closed_trades"] < 3 else f"已平仓样本：{metrics['closed_trades']}笔"
    return "\n".join(
        [
            "【NOVAION｜模拟盘日报｜非真实交易】",
            "",
            "模拟账户：",
            f"初始本金：{_money(metrics['starting_balance'])}",
            f"当前账户余额：{_money(metrics['account_balance'])}",
            f"当前账户权益：{_money(metrics['account_equity'])}",
            f"当前可用资金：{_money(metrics['available_funds'])}",
            *_funding_status_lines(metrics),
            f"当前保证金占用：{_money(metrics['used_margin'])}",
            f"账户累计收益率：{_pct(metrics['account_return_pct'])}",
            "",
            "今日交易：",
            f"新信号：{len(signals)}条",
            f"模拟开仓：{opened}笔",
            f"模拟加仓：{added}次",
            f"模拟减仓：{reduced}次",
            f"模拟平仓：{closed}笔",
            f"当前持仓：{metrics['open_trades']}笔",
            "",
            "今日结果：",
            f"今日已实现盈亏：{_money(today_realized)}",
            f"累计已实现盈亏：{_money(metrics['realized_pnl'])}",
            f"当前预计净浮动盈亏：{_money(metrics['unrealized_pnl'])}",
            f"盈利平仓：{metrics['winning_closed_trades']}笔",
            f"亏损平仓：{metrics['losing_closed_trades']}笔",
            sample_line,
            "",
            "忽略信号：",
            f"高风险：{ignored['high_risk']}条",
            f"无对应仓位：{ignored['orphan']}条",
            f"资金不足：{ignored['insufficient']}条",
            f"数据缺失：{ignored['missing_data']}条",
            "",
            "老板结论：",
            boss_conclusion(metrics),
        ]
    )


def _open_message(title: str, trade: PaperTrade, signal: Signal, wallet: Wallet | None, metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "【NOVAION｜模拟盘｜非真实交易】",
            "",
            title,
            "",
            f"模拟账户本金：{_money(metrics['starting_balance'])}",
            f"本次开仓投入：{_money(trade.size_usd)}",
            f"账户保证金总占用：{_money(metrics['used_margin'])}",
            f"当前可用资金：{_money(metrics['available_funds'])}",
            *_funding_status_lines(metrics),
            "",
            f"使用杠杆：{_leverage(trade.leverage)}倍",
            f"实际模拟仓位：{_money(trade_notional(trade))}",
            f"模拟开仓价格：{_price(trade.entry_price)}",
            "",
            f"来源钱包：{_wallet_label(wallet)}",
            f"风险等级：{_risk_label(signal.risk_score)}",
            "状态：持仓中",
            "",
            "老板结论：",
            f"系统已使用{_pct((trade.size_usd or 0) / metrics['starting_balance'] * 100)}的模拟本金跟踪这条信号，只做模拟验证，不进行真实交易。",
        ]
    )


def _add_message(title: str, trade: PaperTrade, wallet: Wallet | None, metrics: dict[str, Any], payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "【NOVAION｜模拟盘加仓｜非真实交易】",
            "",
            title,
            "",
            f"本次追加投入：{_money(payload.get('added_size_usd', 0))}",
            f"{trade.symbol}仓位保证金：{_money(trade.size_usd)}",
            f"账户保证金总占用：{_money(metrics['used_margin'])}",
            f"当前可用资金：{_money(metrics['available_funds'])}",
            *_funding_status_lines(metrics),
            "",
            f"使用杠杆：{_leverage(trade.leverage)}倍",
            f"当前实际模拟仓位：{_money(trade_notional(trade))}",
            f"最新平均成本：{_price(trade.entry_price)}",
            f"来源钱包：{_wallet_label(wallet)}",
            "",
            "老板结论：",
            "源钱包继续增加仓位，模拟资金占用已提高，继续观察风险。",
        ]
    )


def _reduce_message(title: str, trade: PaperTrade, wallet: Wallet | None, metrics: dict[str, Any], payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "【NOVAION｜模拟盘减仓｜非真实交易】",
            "",
            title,
            "",
            "本次减仓：50%",
            f"本次已实现盈亏：{_money(payload.get('realized_pnl', 0))}",
            f"累计已实现盈亏：{_money(trade.pnl)}",
            "",
            f"当前剩余保证金：{_money(trade.size_usd)}",
            f"当前预计净浮动盈亏：{_money(trade.unrealized_pnl)}",
            f"当前可用资金：{_money(metrics['available_funds'])}",
            *_funding_status_lines(metrics),
            f"来源钱包：{_wallet_label(wallet)}",
            "",
            "剩余状态：继续持有",
            "",
            "老板结论：",
            "系统已降低该模拟仓位风险，部分盈亏已经确认，剩余仓位继续观察。",
        ]
    )


def _close_message(title: str, trade: PaperTrade, wallet: Wallet | None, metrics: dict[str, Any]) -> str:
    outcome = "净盈利" if (trade.pnl or 0) >= 0 else "净亏损"
    conclusion = (
        "这笔模拟跟单已经盈利，但还需要更多样本判断钱包是否长期稳定。"
        if (trade.pnl or 0) >= 0
        else "这笔模拟跟单已经亏损，需要结合整体胜率、回撤和更多样本判断。"
    )
    return "\n".join(
        [
            "【NOVAION｜模拟盘结果｜非真实交易】",
            "",
            f"{trade.symbol} {_side_zh(trade.side)}已平仓",
            "",
            f"模拟账户初始本金：{_money(metrics['starting_balance'])}",
            f"本次累计{outcome}：{_money(trade.pnl)}",
            "",
            f"开仓价格：{_price(trade.entry_price)}",
            f"平仓价格：{_price(trade.exit_price)}",
            "",
            f"当前账户余额：{_money(metrics['account_balance'])}",
            f"当前账户权益：{_money(metrics['account_equity'])}",
            f"当前可用资金：{_money(metrics['available_funds'])}",
            *_funding_status_lines(metrics),
            f"账户累计收益率：{_pct(metrics['account_return_pct'])}",
            f"来源钱包：{_wallet_label(wallet)}",
            "",
            "老板结论：",
            conclusion,
        ]
    )


def _send_text(db: Session, text: str, payload: dict[str, Any]) -> bool:
    settings = get_settings()
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=12,
        )
        response.raise_for_status()
        write_log(db, level="info", module="paper_trading_telegram", message="Boss mode notification sent", payload=payload)
        return True
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="paper_trading_telegram",
            message="Boss mode notification failed",
            payload={**payload, "error": str(exc)},
        )
        return False


def _count_logs(logs: list[SystemLog], action: str) -> int:
    return len([log for log in logs if log.message == action])


def _funding_status_lines(metrics: dict[str, Any]) -> list[str]:
    if metrics.get("available_funds_raw", 0) >= 0:
        return []
    return [
        "账户资金状态：保证金超额占用",
        f"超额占用金额：{_money(metrics.get('over_margin_amount'))}",
        f"保证金占用率：{_pct(metrics.get('margin_utilization_pct'))}",
    ]


def _trade_title(trade: PaperTrade) -> str:
    return f"{trade.symbol} 模拟{_side_zh(trade.side)}"


def _side_zh(side: str) -> str:
    return "做空" if side == "short" else "做多"


def _wallet_label(wallet: Wallet | None) -> str:
    if not wallet:
        return "-"
    address = wallet.address or ""
    return f"{address[:6]}...{address[-4:]}" if len(address) >= 12 else address


def _risk_label(score: int) -> str:
    if score >= 80:
        return "高"
    if score >= 60:
        return "中"
    return "中低"


def _money(value: float | int | None) -> str:
    value = value or 0
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def _leverage(value: float | int | None) -> str:
    value = value or 1
    return f"{value:g}"


def _pct(value: float | int | None) -> str:
    value = value or 0
    return f"{value:.2f}%"


def _price(value: float | int | None) -> str:
    value = value or 0
    return f"{value:.5f}"
