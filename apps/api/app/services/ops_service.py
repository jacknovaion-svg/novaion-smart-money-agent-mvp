from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.ops import HyperliquidApiMetric, TaskLock
from app.models.signal import DailyReport, PaperTrade, Signal
from app.models.system_log import SystemLog
from app.models.wallet import Wallet
from app.services.system_log_service import write_log


def run_with_task_lock(db: Session, task_name: str, fn: Callable[..., Any]) -> Any:
    now = datetime.now(timezone.utc)
    lock = db.query(TaskLock).filter(TaskLock.task_name == task_name).first()
    stale_after = now - timedelta(minutes=get_settings().task_lock_stale_minutes)
    if lock and lock.status == "running" and lock.heartbeat_at and lock.heartbeat_at > stale_after:
        write_log(db, level="info", module="task_lock", message="Task skipped because lock is running", payload={"task": task_name})
        return {"skipped": True}
    if not lock:
        lock = TaskLock(task_name=task_name)
        db.add(lock)
    lock.status = "running"
    lock.started_at = now
    lock.finished_at = None
    lock.heartbeat_at = now
    lock.error_message = ""
    db.commit()
    try:
        result = _call_with_optional_heartbeat(fn, lambda: update_task_heartbeat(db, task_name))
        lock.status = "ok"
        lock.finished_at = datetime.now(timezone.utc)
        lock.heartbeat_at = lock.finished_at
        db.commit()
        return result
    except Exception as exc:
        lock.status = "failed"
        lock.error_message = str(exc)[:1000]
        lock.finished_at = datetime.now(timezone.utc)
        lock.heartbeat_at = lock.finished_at
        db.commit()
        raise


def update_task_heartbeat(db: Session, task_name: str) -> datetime:
    lock = db.query(TaskLock).filter(TaskLock.task_name == task_name).first()
    if not lock:
        lock = TaskLock(task_name=task_name, status="running")
        db.add(lock)
    lock.heartbeat_at = datetime.now(timezone.utc)
    db.commit()
    return lock.heartbeat_at


def _call_with_optional_heartbeat(fn: Callable[..., Any], heartbeat: Callable[[], datetime]) -> Any:
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        parameters = {}
    if parameters:
        return fn(heartbeat)
    return fn()


def record_hyperliquid_metric(db: Session, *, success: bool, latency_ms: float, error: str = "") -> None:
    bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    metric = db.query(HyperliquidApiMetric).filter(HyperliquidApiMetric.minute_bucket == bucket).first()
    if not metric:
        metric = HyperliquidApiMetric(minute_bucket=bucket)
        db.add(metric)
    metric.request_count = (metric.request_count or 0) + 1
    metric.total_latency_ms = (metric.total_latency_ms or 0) + latency_ms
    if success:
        metric.success_count = (metric.success_count or 0) + 1
    else:
        metric.failure_count = (metric.failure_count or 0) + 1
        lower = error.lower()
        if "timeout" in lower or "timed out" in lower:
            metric.timeout_count = (metric.timeout_count or 0) + 1
        if "429" in lower or "rate" in lower:
            metric.rate_limit_count = (metric.rate_limit_count or 0) + 1
    db.commit()


def hyperliquid_api_summary(db: Session) -> dict[str, Any]:
    rows = db.query(HyperliquidApiMetric).order_by(HyperliquidApiMetric.minute_bucket.desc()).limit(60).all()
    request_count = sum(row.request_count for row in rows)
    success_count = sum(row.success_count for row in rows)
    failure_count = sum(row.failure_count for row in rows)
    latency = sum(row.total_latency_ms for row in rows)
    return {
        "request_count": request_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "timeout_count": sum(row.timeout_count for row in rows),
        "rate_limit_count": sum(row.rate_limit_count for row in rows),
        "success_rate": round(success_count / request_count * 100, 2) if request_count else 0,
        "error_rate": round(failure_count / request_count * 100, 2) if request_count else 0,
        "avg_response_ms": round(latency / request_count, 2) if request_count else 0,
    }


def validation_readiness(db: Session, health: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    wallets_count = db.query(Wallet).filter(Wallet.status == "active").count()
    candidates = db.query(DiscoveryCandidate).count()
    recommended = db.query(DiscoveryCandidate).filter(DiscoveryCandidate.status == "recommended").count()
    reasons = []
    if wallets_count < 5:
        reasons.append("wallets_count_below_5")
    if candidates < 20:
        reasons.append("discovery_candidates_below_20")
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        reasons.append("telegram_not_configured")
    if health.get("scheduler_status") != "running":
        reasons.append("scheduler_not_running")
    if health.get("overall_status") == "critical":
        reasons.append("health_status_critical")
    return {
        "wallets_count": wallets_count,
        "discovery_candidates_count": candidates,
        "recommended_count": recommended,
        "signals_count": db.query(Signal).count(),
        "paper_trades_count": db.query(PaperTrade).count(),
        "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "scheduler_running": health.get("scheduler_status") == "running",
        "health_status": health.get("overall_status", "warning"),
        "can_start_7_day_validation": not reasons,
        "blocking_reasons": reasons,
    }


def validation_dashboard(db: Session) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    days = []
    for offset in range(get_settings().validation_days):
        day = today - timedelta(days=get_settings().validation_days - offset - 1)
        day_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        signals = db.query(Signal).filter(Signal.created_at >= day_start, Signal.created_at < day_end).all()
        trades = db.query(PaperTrade).filter(PaperTrade.opened_at >= day_start, PaperTrade.opened_at < day_end).all()
        closed = [trade for trade in trades if trade.status == "closed"]
        wins = [trade for trade in closed if trade.pnl > 0]
        reports = db.query(DailyReport).filter(DailyReport.created_at >= day_start, DailyReport.created_at < day_end).all()
        recommended_wallet_ids = {
            item.added_wallet_id
            for item in db.query(DiscoveryCandidate).filter(DiscoveryCandidate.status.in_(["recommended", "approved"])).all()
            if item.added_wallet_id
        }
        watch_wallet_ids = {
            item.added_wallet_id
            for item in db.query(DiscoveryCandidate).filter(DiscoveryCandidate.grade == "Watch").all()
            if item.added_wallet_id
        }
        recommended_pnl = sum(trade.pnl for trade in trades if trade.wallet_id in recommended_wallet_ids)
        watch_pnl = sum(trade.pnl for trade in trades if trade.wallet_id in watch_wallet_ids)
        baseline_pnl = sum(trade.pnl for trade in trades)
        max_dd = _max_drawdown([trade.pnl for trade in sorted(trades, key=lambda item: item.closed_at or item.opened_at)])
        days.append(
            {
                "day": f"Day{offset + 1}",
                "date": str(day),
                "signals_count": len(signals),
                "paper_trades_count": len(trades),
                "pnl": round(sum(trade.pnl for trade in trades), 6),
                "win_rate": round(len(wins) / len(closed) * 100, 2) if closed else 0,
                "max_drawdown": max_dd,
                "recommended_wallets_future_pnl": round(recommended_pnl, 6),
                "watch_wallets_future_pnl": round(watch_pnl, 6),
                "all_candidates_baseline_pnl": round(baseline_pnl, 6),
                "recommended_vs_baseline_comparison": round(recommended_pnl - baseline_pnl, 6),
                "best_wallet": reports[-1].best_wallet if reports else "",
                "worst_wallet": reports[-1].worst_wallet if reports else "",
                "recommended_wallets": db.query(DiscoveryCandidate).filter(DiscoveryCandidate.status == "recommended").count(),
                "rejected_wallets": db.query(DiscoveryCandidate).filter(DiscoveryCandidate.grade == "Reject").count(),
                "system_health_status": "ok",
            }
        )
    return {"validation_mode": get_settings().validation_mode, "days": days}


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return round(drawdown, 6)


def count_logs(db: Session, *, module: str | None = None, level: str | None = None, message: str | None = None, since=None) -> int:
    query = db.query(SystemLog)
    if module:
        query = query.filter(SystemLog.module == module)
    if level:
        query = query.filter(SystemLog.level == level.upper())
    if message:
        query = query.filter(SystemLog.message == message)
    if since:
        query = query.filter(SystemLog.created_at >= since)
    return query.count()
