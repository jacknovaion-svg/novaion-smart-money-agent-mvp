from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.signal import Signal
from app.models.system_log import SystemLog
from app.models.wallet import Wallet
from app.services.system_log_service import write_log


def send_signal_notification(db: Session, signal: Signal, wallet: Wallet) -> bool:
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


def send_daily_report_notification(db: Session, report) -> bool:
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
