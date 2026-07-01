from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.signal import PaperTrade
from app.models.signal import Signal
from app.models.system_log import SystemLog
from app.models.wallet import Wallet
from app.services.paper_account_service import paper_account_metrics
from app.services.system_log_service import write_log


def send_signal_notification(db: Session, signal: Signal, wallet: Wallet) -> bool:
    settings = get_settings()
    if settings.smart_money_telegram_boss_mode:
        flush_signal_aggregation_notifications(db)
        return _send_boss_signal_notification(db, signal, wallet)

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        write_log(
            db,
            level="info",
            module="telegram",
            message="Telegram not configured; signal notification skipped",
            payload={"signal_id": signal.id},
        )
        return False

    text = _format_signal_message(signal, wallet)
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=12,
        )
        response.raise_for_status()
        signal.telegram_sent_at = datetime.now(timezone.utc)
        db.commit()
        write_log(
            db,
            level="info",
            module="telegram",
            message="Signal notification sent",
            payload={"signal_id": signal.id},
        )
        return True
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="telegram",
            message="Signal notification failed",
            payload={"signal_id": signal.id, "error": str(exc)},
        )
        return False


def flush_signal_aggregation_notifications(db: Session, *, now: datetime | None = None) -> int:
    settings = get_settings()
    if not settings.smart_money_telegram_boss_mode:
        return 0
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return 0
    now = _as_utc(now or datetime.now(timezone.utc))
    cutoff = now - timedelta(minutes=settings.smart_money_telegram_aggregation_minutes)
    queued_signal_ids = _queued_aggregation_signal_ids(db, cutoff)
    if not queued_signal_ids:
        return 0
    pending = (
        db.query(Signal)
        .filter(Signal.signal_type.in_(["add", "reduce"]))
        .filter(Signal.id.in_(queued_signal_ids))
        .filter(Signal.telegram_sent_at.is_(None))
        .filter(Signal.created_at <= cutoff)
        .order_by(Signal.wallet_id.asc(), Signal.symbol.asc(), Signal.side.asc(), Signal.created_at.asc())
        .all()
    )
    grouped: dict[tuple[int, str, str], list[Signal]] = {}
    for signal in pending:
        side = _position_side(signal)
        grouped.setdefault((signal.wallet_id, signal.symbol, side), []).append(signal)

    sent = 0
    for signals in grouped.values():
        if _send_aggregation_notification(db, signals, now=now):
            sent += 1
    return sent


def _send_boss_signal_notification(db: Session, signal: Signal, wallet: Wallet) -> bool:
    if signal.signal_type in {"add", "reduce"}:
        write_log(
            db,
            level="info",
            module="telegram",
            message="Smart money signal queued for aggregation",
            payload={
                "signal_id": signal.id,
                "wallet_id": signal.wallet_id,
                "symbol": signal.symbol,
                "signal_type": signal.signal_type,
                "aggregation_key": _aggregation_key(signal),
            },
        )
        return False
    if signal.risk_score > 80 or (signal.suggested_size_usd or 0) <= 0:
        write_log(
            db,
            level="info",
            module="telegram",
            message="Smart money signal notification suppressed",
            payload={"signal_id": signal.id, "reason": "risk_or_zero_size"},
        )
        return False
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        write_log(
            db,
            level="info",
            module="telegram",
            message="Telegram not configured; signal notification skipped",
            payload={"signal_id": signal.id},
        )
        return False

    text = _format_boss_signal_message(db, signal, wallet)
    return _send_signal_text(db, signal, text, "Signal notification sent", {"mode": "boss"})


def _send_aggregation_notification(db: Session, signals: list[Signal], *, now: datetime) -> bool:
    if not signals:
        return False
    wallet = db.query(Wallet).filter(Wallet.id == signals[0].wallet_id).first()
    if not wallet:
        return False
    text = _format_aggregation_message(db, signals, wallet)
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{get_settings().telegram_bot_token}/sendMessage",
            json={"chat_id": get_settings().telegram_chat_id, "text": text},
            timeout=12,
        )
        response.raise_for_status()
        for signal in signals:
            signal.telegram_sent_at = now
            db.add(signal)
        db.commit()
        write_log(
            db,
            level="info",
            module="telegram",
            message="Smart money aggregation notification sent",
            payload={
                "aggregation_key": _aggregation_key(signals[0]),
                "signal_ids": [signal.id for signal in signals],
                "count": len(signals),
            },
        )
        return True
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="telegram",
            message="Smart money aggregation notification failed",
            payload={"signal_ids": [signal.id for signal in signals], "error": str(exc)},
        )
        return False


def _format_signal_message(signal: Signal, wallet: Wallet) -> str:
    action = f"{signal.symbol} {signal.side.title()} / {signal.signal_type.title()}"
    return "\n".join(
        [
            "[NOVAION Smart Money Signal]",
            f"钱包：{wallet.name}",
            f"标签：{wallet.tags or '-'}",
            f"动作：{action}",
            f"高手仓位：${signal.source_size:,.2f}",
            f"杠杆：{signal.source_leverage:g}x",
            f"当前价格：{signal.current_price:g}",
            f"信心评分：{signal.confidence_score}",
            f"风险评分：{signal.risk_score}",
            f"系统建议：{signal.suggested_action}",
            f"建议模拟金额：${signal.suggested_size_usd:g}",
            f"原因：{signal.reason}",
        ]
    )


def _format_boss_signal_message(db: Session, signal: Signal, wallet: Wallet) -> str:
    if signal.signal_type == "close":
        side = _latest_position_side(db, signal) or "close"
        paper_result = _paper_result_for_signal(db, signal)
        return "\n".join(
            [
                "【聪明钱已平仓】",
                "",
                f"钱包：{_short_wallet(wallet)}",
                f"币种：{signal.symbol}",
                f"方向：{_side_zh(side)}",
                "动作：完全平仓",
                "",
                "源钱包动作：",
                f"已退出 {signal.symbol} {_side_zh(side)}仓位",
                "",
                "系统模拟动作：",
                paper_result,
                "",
                "老板结论：",
                "该钱包已退出该方向，本次模拟结果已经确认。",
            ]
        )
    previous_side = _latest_position_side(db, signal)
    current_side = _position_side(signal)
    if signal.signal_type == "open" and previous_side and previous_side != current_side:
        return "\n".join(
            [
                "【重点提醒｜方向反转】",
                "",
                f"钱包：{_short_wallet(wallet)}",
                f"币种：{signal.symbol}",
                "",
                "源钱包动作：",
                f"原方向：{_side_zh(previous_side)}",
                f"新方向：{_side_zh(current_side)}",
                "",
                "系统模拟动作：",
                _paper_action_for_signal(db, signal),
                "",
                "老板结论：",
                "该钱包已经改变方向，需要重点关注后续仓位变化。",
            ]
        )
    return "\n".join(
        [
            "【聪明钱新开仓】",
            "",
            f"钱包：{_short_wallet(wallet)}",
            f"币种：{signal.symbol}",
            f"方向：{_side_zh(current_side)}",
            "动作：新开仓",
            "",
            "源钱包动作：",
            f"新建 {signal.symbol} {_side_zh(current_side)}仓位，仓位约 {_money(signal.source_size)}",
            f"信号价格：{_price(signal.current_price or signal.source_entry_price)}",
            f"风险等级：{_risk_label(signal.risk_score)}",
            "",
            "系统模拟动作：",
            _paper_action_for_signal(db, signal),
            "",
            "老板结论：",
            f"该钱包建立了新的{_side_zh(current_side)}方向，开始观察。",
        ]
    )


def _format_aggregation_message(db: Session, signals: list[Signal], wallet: Wallet) -> str:
    first = signals[0]
    add_count = len([signal for signal in signals if signal.signal_type == "add"])
    reduce_count = len([signal for signal in signals if signal.signal_type == "reduce"])
    first_size = signals[0].source_size or 0
    last_size = signals[-1].source_size or 0
    action = _aggregate_system_action(db, signals)
    side = _position_side(first)
    conclusion = _aggregate_conclusion(side, add_count, reduce_count)
    return "\n".join(
        [
            "【聪明钱仓位动态】",
            "",
            f"钱包：{_short_wallet(wallet)}",
            f"币种：{first.symbol}",
            f"方向：{_side_zh(side)}",
            "",
            f"过去{get_settings().smart_money_telegram_aggregation_minutes}分钟：",
            f"加仓：{add_count}次",
            f"减仓：{reduce_count}次",
            "",
            "源钱包仓位：",
            f"{_money(first_size)} → {_money(last_size)}",
            "",
            "系统模拟动作：",
            action,
            "",
            "老板结论：",
            conclusion,
        ]
    )


def send_daily_report_notification(db: Session, report) -> bool:
    settings = get_settings()
    if settings.smart_money_telegram_boss_mode:
        flush_signal_aggregation_notifications(db)
        return _send_boss_daily_report_notification(db, report)
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        write_log(
            db,
            level="info",
            module="telegram",
            message="Telegram not configured; daily report skipped",
            payload={"report_id": report.id},
        )
        return False
    text = "\n".join(
        [
            "[NOVAION Daily Inner Test Report]",
            f"日期：{report.report_date}",
            f"今日信号数量：{report.signal_count}",
            f"今日模拟盈亏：${report.simulated_pnl:,.2f}",
            f"今日最佳钱包：{report.best_wallet or '-'}",
            f"今日最差钱包：{report.worst_wallet or '-'}",
            f"建议：{report.live_test_recommendation}",
            "提示：继续模拟验证，不接私钥，不自动实盘。",
        ]
    )
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=12,
        )
        response.raise_for_status()
        report.telegram_sent_at = datetime.now(timezone.utc)
        db.commit()
        write_log(
            db,
            level="info",
            module="telegram",
            message="Daily report notification sent",
            payload={"report_id": report.id},
        )
        return True
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="telegram",
            message="Daily report notification failed",
            payload={"report_id": report.id, "error": str(exc)},
        )
        return False


def _send_boss_daily_report_notification(db: Session, report) -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        write_log(
            db,
            level="info",
            module="telegram",
            message="Telegram not configured; daily report skipped",
            payload={"report_id": report.id},
        )
        return False
    text = _format_boss_daily_report(db, report)
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=12,
        )
        response.raise_for_status()
        report.telegram_sent_at = datetime.now(timezone.utc)
        db.commit()
        write_log(
            db,
            level="info",
            module="telegram",
            message="Daily report notification sent",
            payload={"report_id": report.id, "mode": "boss"},
        )
        return True
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="telegram",
            message="Daily report notification failed",
            payload={"report_id": report.id, "error": str(exc)},
        )
        return False


def _format_boss_daily_report(db: Session, report) -> str:
    day_start = _as_utc(datetime.fromisoformat(str(report.report_date))).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    signals = (
        db.query(Signal)
        .filter(Signal.created_at >= day_start)
        .filter(Signal.created_at < day_end)
        .all()
    )
    open_count = len([signal for signal in signals if signal.signal_type == "open"])
    close_count = len([signal for signal in signals if signal.signal_type == "close"])
    add_reduce_groups = {
        _aggregation_key(signal) for signal in signals if signal.signal_type in {"add", "reduce"}
    }
    open_paper = (
        db.query(PaperTrade)
        .filter(PaperTrade.opened_at >= day_start)
        .filter(PaperTrade.opened_at < day_end)
        .count()
    )
    closed_paper = (
        db.query(PaperTrade)
        .filter(PaperTrade.closed_at >= day_start)
        .filter(PaperTrade.closed_at < day_end)
        .count()
    )
    metrics = paper_account_metrics(db)
    ignored = _ignored_reason_counts(db, day_start, day_end)
    conclusion = _daily_conclusion(metrics, report)
    return "\n".join(
        [
            "【NOVAION｜每日汇总｜非真实交易】",
            "",
            "今日聪明钱信号：",
            f"新开仓：{open_count}条",
            f"完全平仓：{close_count}条",
            f"Add / Reduce 聚合摘要：{len(add_reduce_groups)}组",
            "",
            "模拟盘：",
            f"模拟开仓：{open_paper}笔",
            f"模拟平仓：{closed_paper}笔",
            f"当前持仓：{metrics['open_trades']}笔",
            "",
            "盈亏：",
            f"今日已实现盈亏：{_money(report.simulated_pnl)}",
            f"当前未实现盈亏：{_money(metrics['unrealized_pnl'])}",
            "",
            "忽略信号：",
            f"今日忽略：{sum(ignored.values())}条",
            "主要原因：",
            f"资金不足：{ignored['funds']}",
            f"无对应模拟仓位：{ignored['orphan']}",
            f"风险过高：{ignored['risk']}",
            f"数据缺失：{ignored['missing']}",
            "",
            "钱包表现：",
            f"表现最好：{_text_or_dash(report.best_wallet)}",
            f"表现最差：{_text_or_dash(report.worst_wallet)}",
            "",
            "老板结论：",
            conclusion,
        ]
    )


def send_ops_alert(db: Session, title: str, message: str, payload: dict | None = None) -> bool:
    settings = get_settings()
    cooldown_since = datetime.now(timezone.utc) - timedelta(minutes=settings.alert_cooldown_minutes)
    recent = (
        db.query(SystemLog)
        .filter(SystemLog.module == "telegram", SystemLog.message == "Ops alert sent", SystemLog.created_at >= cooldown_since)
        .filter(SystemLog.payload_json.contains(f'"title": "{title}"'))
        .first()
    )
    if recent:
        write_log(db, level="warning", module="telegram", message="Ops alert suppressed by cooldown", payload={"title": title})
        return False
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        write_log(
            db,
            level="info",
            module="telegram",
            message="Telegram not configured; ops alert skipped",
            payload={"title": title, **(payload or {})},
        )
        return False
    text = "\n".join(["[NOVAION Ops Alert]", title, message, "No private keys. No live trading."])
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=12,
        )
        response.raise_for_status()
        write_log(db, level="info", module="telegram", message="Ops alert sent", payload={"title": title, **(payload or {})})
        return True
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="telegram",
            message="Ops alert failed",
            payload={"title": title, "error": str(exc), **(payload or {})},
        )
        return False


def _send_signal_text(db: Session, signal: Signal, text: str, message: str, payload: dict[str, Any] | None = None) -> bool:
    settings = get_settings()
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=12,
        )
        response.raise_for_status()
        signal.telegram_sent_at = datetime.now(timezone.utc)
        db.commit()
        write_log(
            db,
            level="info",
            module="telegram",
            message=message,
            payload={"signal_id": signal.id, **(payload or {})},
        )
        return True
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="telegram",
            message="Signal notification failed",
            payload={"signal_id": signal.id, "error": str(exc), **(payload or {})},
        )
        return False


def _aggregation_key(signal: Signal) -> str:
    return f"{signal.wallet_id}:{signal.symbol}:{_position_side(signal)}"


def _position_side(signal: Signal) -> str:
    return signal.side if signal.side in {"long", "short"} else "close"


def _latest_position_side(db: Session, signal: Signal) -> str | None:
    previous = (
        db.query(Signal)
        .filter(Signal.wallet_id == signal.wallet_id)
        .filter(Signal.symbol == signal.symbol)
        .filter(Signal.id != signal.id)
        .filter(Signal.created_at < signal.created_at)
        .filter(Signal.side.in_(["long", "short"]))
        .order_by(Signal.created_at.desc(), Signal.id.desc())
        .first()
    )
    return previous.side if previous else None


def _paper_action_for_signal(db: Session, signal: Signal) -> str:
    log = _latest_paper_log(db, signal.id)
    if log:
        return _paper_log_to_action(log)
    if signal.suggested_size_usd and signal.suggested_size_usd > 0:
        return f"等待模拟处理，建议模拟金额 {_money(signal.suggested_size_usd)}"
    return "未进入模拟，等待更多有效数据"


def _paper_result_for_signal(db: Session, signal: Signal) -> str:
    log = _latest_paper_log(db, signal.id)
    if log and log.message == "paper_closed":
        payload = _payload(log)
        pnl = float(payload.get("realized_pnl") or 0)
        return f"模拟仓位已平仓，净{'盈利' if pnl >= 0 else '亏损'} {_money(abs(pnl))}"
    if log:
        return _paper_log_to_action(log)
    return "没有对应模拟仓位，已记录到汇总"


def _aggregate_system_action(db: Session, signals: list[Signal]) -> str:
    logs = [_latest_paper_log(db, signal.id) for signal in signals]
    messages = [log.message for log in logs if log]
    if "insufficient_paper_funds" in messages:
        return "因模拟资金不足，未继续加仓"
    added = len([message for message in messages if message == "paper_added"])
    reduced = len([message for message in messages if message == "paper_reduced"])
    if added and reduced:
        return f"已模拟加仓 {added} 次、减仓 {reduced} 次"
    if added:
        return f"已模拟加仓 {added} 次"
    if reduced:
        return f"已按规则减少模拟仓位 {reduced} 次"
    if any(message in {"orphan_add", "orphan_reduce", "orphan_close"} for message in messages):
        return "没有对应模拟仓位，未执行模拟动作"
    return "未触发模拟动作，已记录到每日汇总"


def _latest_paper_log(db: Session, signal_id: int) -> SystemLog | None:
    pattern = f'"signal_id": {signal_id}'
    return (
        db.query(SystemLog)
        .filter(SystemLog.module.in_(["paper_trading", "paper_trading_telegram"]))
        .filter(SystemLog.payload_json.contains(pattern))
        .order_by(SystemLog.created_at.desc(), SystemLog.id.desc())
        .first()
    )


def _paper_log_to_action(log: SystemLog) -> str:
    payload = _payload(log)
    if log.message == "paper_opened":
        return f"已模拟投入 {_money(payload.get('requested_margin') or 20)}"
    if log.message == "paper_added":
        return f"已模拟加仓 {_money(payload.get('added_size_usd'))}"
    if log.message == "paper_reduced":
        return "已按规则减少模拟仓位"
    if log.message == "paper_closed":
        pnl = float(payload.get("realized_pnl") or 0)
        return f"模拟仓位已平仓，净{'盈利' if pnl >= 0 else '亏损'} {_money(abs(pnl))}"
    if log.message == "insufficient_paper_funds":
        return "因模拟资金不足，未执行模拟开仓或加仓"
    if log.message in {"orphan_add", "orphan_reduce", "orphan_close"}:
        return "没有对应模拟仓位，未执行模拟动作"
    return "已记录，等待模拟处理"


def _ignored_reason_counts(db: Session, day_start: datetime, day_end: datetime) -> dict[str, int]:
    counts = {"funds": 0, "orphan": 0, "risk": 0, "missing": 0}
    logs = (
        db.query(SystemLog)
        .filter(SystemLog.created_at >= day_start)
        .filter(SystemLog.created_at < day_end)
        .filter(SystemLog.module == "paper_trading")
        .all()
    )
    for log in logs:
        if log.message == "insufficient_paper_funds":
            counts["funds"] += 1
        elif log.message in {"orphan_add", "orphan_reduce", "orphan_close", "ambiguous_close"}:
            counts["orphan"] += 1
        elif log.message == "high_risk":
            counts["risk"] += 1
        elif log.message in {"missing_data", "zero_size"}:
            counts["missing"] += 1
    return counts


def _queued_aggregation_signal_ids(db: Session, cutoff: datetime) -> set[int]:
    logs = (
        db.query(SystemLog)
        .filter(SystemLog.module == "telegram")
        .filter(SystemLog.message == "Smart money signal queued for aggregation")
        .all()
    )
    signal_ids = set()
    for log in logs:
        signal_id = _payload(log).get("signal_id")
        if signal_id:
            signal_ids.add(int(signal_id))
    return signal_ids


def _aggregate_conclusion(side: str, add_count: int, reduce_count: int) -> str:
    side_text = _side_zh(side)
    if reduce_count > add_count:
        return f"该钱包正在持续降低仓位，当前{side_text}信心减弱。"
    if add_count > reduce_count:
        return f"该钱包正在增强{side_text}仓位，方向信心上升，但仍需继续观察风险。"
    return "该钱包仓位有来回调整，暂不判断方向强弱。"


def _daily_conclusion(metrics: dict[str, Any], report) -> str:
    if metrics["closed_trades"] < 3:
        return "当前样本仍需继续观察，不判断策略胜率。"
    if metrics["account_return_pct"] <= -5:
        return "当前账户回撤较高，需要重点关注。"
    if metrics["account_return_pct"] < 0:
        return "账户整体小幅亏损，暂不调整。"
    return "账户整体盈利，继续观察稳定性。"


def _short_wallet(wallet: Wallet) -> str:
    address = wallet.address or wallet.name or "-"
    if len(address) >= 10 and address.startswith("0x"):
        return f"{address[:6]}...{address[-4:]}"
    return address


def _money(value: Any) -> str:
    try:
        number = float(value or 0)
    except Exception:
        number = 0
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):,.2f}"


def _price(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except Exception:
        return "-"


def _risk_label(score: int | float | None) -> str:
    score = int(score or 0)
    if score <= 35:
        return "低"
    if score <= 60:
        return "中低"
    if score <= 80:
        return "中高"
    return "高"


def _side_zh(side: str | None) -> str:
    if side == "short":
        return "做空"
    if side == "long":
        return "做多"
    return "平仓"


def _text_or_dash(value: Any) -> str:
    return str(value) if value else "-"


def _payload(log: SystemLog) -> dict[str, Any]:
    try:
        return json.loads(log.payload_json or "{}")
    except Exception:
        return {}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
