import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.scheduler import scheduler
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.market_data import SyncState, WalletFill, WalletPositionSnapshot
from app.models.ops import TaskLock
from app.models.signal import DailyReport, PaperTrade, Signal
from app.models.system_log import SystemLog
from app.models.wallet import Wallet
from app.services.ops_service import count_logs, hyperliquid_api_summary


STARTED_AT = datetime.now(timezone.utc)


def system_health(db: Session) -> dict[str, Any]:
    started = time.monotonic()
    database_ok = _database_ok(db)
    query_latency_ms = round((time.monotonic() - started) * 1000, 2)
    now = datetime.now(timezone.utc)
    last_sync = db.query(SyncState).order_by(SyncState.updated_at.desc()).first()
    last_discovery = db.query(DiscoveryRun).order_by(DiscoveryRun.started_at.desc()).first()
    last_signal = db.query(Signal).order_by(Signal.created_at.desc()).first()
    last_report = db.query(DailyReport).order_by(DailyReport.created_at.desc()).first()
    last_fill = db.query(WalletFill).order_by(WalletFill.trade_time.desc()).first()
    last_position = db.query(WalletPositionSnapshot).order_by(WalletPositionSnapshot.created_at.desc()).first()
    locks = {lock.task_name: lock for lock in db.query(TaskLock).all()}
    recent_since = now - timedelta(hours=24)
    settings = get_settings()
    wallet_sync_status = _lag_status(last_sync.updated_at if last_sync else None, warning_minutes=5, critical_minutes=15)
    discovery_status = _lag_status(last_discovery.finished_at if last_discovery else None, warning_minutes=540, critical_minutes=720)
    scheduler_status = "running" if scheduler.running else "stopped"
    statuses = [
        "ok" if database_ok else "critical",
        "ok" if scheduler_status == "running" else "warning",
        wallet_sync_status,
        discovery_status,
    ]
    overall = "critical" if "critical" in statuses else ("warning" if "warning" in statuses else "ok")
    return {
        "checked_at": now,
        "overall_status": overall,
        "uptime": str(now - STARTED_AT).split(".")[0],
        "api_status": "ok",
        "database_status": "ok" if database_ok else "error",
        "scheduler_status": scheduler_status,
        "telegram_status": "configured" if settings.telegram_bot_token and settings.telegram_chat_id else "not_configured",
        "hyperliquid_api_status": _hyperliquid_status(db),
        "discovery_status": discovery_status,
        "wallet_sync_status": wallet_sync_status,
        "paper_trading_status": "ok",
        "last_wallet_sync_at": last_sync.updated_at if last_sync else None,
        "last_discovery_run_at": last_discovery.finished_at if last_discovery else None,
        "last_signal_generated_at": last_signal.created_at if last_signal else None,
        "last_daily_report_at": last_report.created_at if last_report else None,
        "last_fills_at": last_fill.trade_time if last_fill else None,
        "last_positions_at": last_position.created_at if last_position else None,
        "wallet_sync_success_count": count_logs(db, module="wallet_sync", level="INFO"),
        "wallet_sync_failure_count": count_logs(db, module="wallet_sync", level="ERROR") + count_logs(db, module="scheduler", level="ERROR", message="Hyperliquid sync job failed"),
        "discovery_success_count": db.query(DiscoveryRun).filter(DiscoveryRun.status == "ok").count(),
        "discovery_failure_count": db.query(DiscoveryRun).filter(DiscoveryRun.status == "failed").count(),
        "telegram_success_count": count_logs(db, module="telegram", level="INFO", message="Ops alert sent"),
        "telegram_failure_count": count_logs(db, module="telegram", level="ERROR"),
        "system_error_count_24h": count_logs(db, level="ERROR", since=recent_since),
        "heartbeat": {name: _heartbeat(lock) for name, lock in locks.items()},
        "hyperliquid_api": hyperliquid_api_summary(db),
        "database": {
            "query_latency_ms": query_latency_ms,
            "dashboard_query_warning": query_latency_ms > 2000,
            "tables": {
                "wallet_equity_snapshots": db.query(WalletPositionSnapshot).count(),
                "discovery_candidates": db.query(DiscoveryCandidate).count(),
                "signals": db.query(Signal).count(),
                "paper_trades": db.query(PaperTrade).count(),
            },
        },
        "signals_count": db.query(Signal).count(),
        "paper_trades_count": db.query(PaperTrade).count(),
        "wallets_count": db.query(Wallet).filter(Wallet.status != "deleted").count(),
        "watchlist_count": db.query(Wallet).filter(Wallet.status == "active").count(),
        "discovery_candidates_count": db.query(DiscoveryCandidate).count(),
        "recommended_count": db.query(DiscoveryCandidate).filter(DiscoveryCandidate.status == "recommended").count(),
    }


def _database_ok(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _lag_status(value, *, warning_minutes: int, critical_minutes: int) -> str:
    if not value:
        return "not_run"
    now = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    age = now - value
    if age > timedelta(minutes=critical_minutes):
        return "critical"
    if age > timedelta(minutes=warning_minutes):
        return "warning"
    return "ok"


def _heartbeat(lock: TaskLock) -> dict[str, Any]:
    status = _lag_status(lock.heartbeat_at, warning_minutes=5, critical_minutes=15)
    return {
        "status": lock.status,
        "heartbeat_status": status,
        "last_updated_at": lock.heartbeat_at,
        "started_at": lock.started_at,
        "finished_at": lock.finished_at,
        "error_message": lock.error_message,
    }


def _hyperliquid_status(db: Session) -> str:
    summary = hyperliquid_api_summary(db)
    if summary["request_count"] == 0:
        return "not_run"
    if summary["error_rate"] >= 50:
        return "critical"
    if summary["error_rate"] >= 10:
        return "warning"
    return "ok"
