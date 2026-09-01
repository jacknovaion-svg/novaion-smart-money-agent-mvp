from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.discovery_service import run_wallet_discovery
from app.services.ops_service import run_with_task_lock
from app.services.paper_trading_processor import process_new_signals_for_paper_trading, update_open_paper_trades
from app.services.quality_service import generate_daily_report, update_signal_performance
from app.services.system_log_service import write_log
from app.services.v2_validation_service import process_new_signals_for_shadow, record_equity_snapshot, update_shadow_positions
from app.services.telegram_service import flush_signal_aggregation_notifications, send_ops_alert
from app.services.wallet_sync_service import recalculate_enabled_wallet_metrics, sync_enabled_hyperliquid_wallets


scheduler = BackgroundScheduler(timezone="UTC")


def start_scheduler() -> None:
    settings = get_settings()
    if not settings.scheduler_enabled or scheduler.running:
        return
    scheduler.add_job(
        _sync_wallets_job,
        "interval",
        minutes=5 if settings.validation_mode else 2,
        id="sync_enabled_hyperliquid_wallets",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _metrics_job,
        "interval",
        minutes=10,
        id="recalculate_wallet_metrics",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _quality_job,
        "interval",
        minutes=15,
        id="update_signal_performance",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(_daily_report_job, "cron", hour=8 if settings.validation_mode else 23, minute=0 if settings.validation_mode else 55, id="generate_daily_report", replace_existing=True, max_instances=1)
    if settings.validation_mode:
        scheduler.add_job(_discovery_job, "interval", hours=8, id="wallet_discovery", replace_existing=True, max_instances=1)
        scheduler.add_job(_paper_trade_update_job, "interval", minutes=15, id="paper_trade_update", replace_existing=True, max_instances=1)
        scheduler.add_job(_health_report_job, "cron", hour=20, minute=0, id="health_report", replace_existing=True, max_instances=1)
        if settings.v2_alpha_validation_enabled:
            scheduler.add_job(_v2_equity_snapshot_job, "interval", minutes=15, id="v2_equity_snapshot", replace_existing=True, max_instances=1)
            if settings.shadow_trading_enabled:
                scheduler.add_job(_shadow_trade_job, "interval", minutes=5, id="v2_shadow_trade_processor", replace_existing=True, max_instances=1)
    else:
        scheduler.add_job(_discovery_job, "cron", hour=2, minute=15, id="wallet_discovery", replace_existing=True, max_instances=1)
    scheduler.start()


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def _sync_wallets_job() -> None:
    db = SessionLocal()
    try:
        if get_settings().hyperliquid_sync_enabled:
            run_with_task_lock(db, "wallet_sync", lambda: sync_enabled_hyperliquid_wallets(db))
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="scheduler",
            message="Hyperliquid sync job failed",
            payload={"error": str(exc)},
        )
        send_ops_alert(db, "Wallet Sync Failed", str(exc), {"job": "sync_enabled_hyperliquid_wallets"})
    finally:
        db.close()


def _metrics_job() -> None:
    db = SessionLocal()
    try:
        run_with_task_lock(db, "wallet_metrics", lambda: recalculate_enabled_wallet_metrics(db))
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="scheduler",
            message="Metrics job failed",
            payload={"error": str(exc)},
        )
        send_ops_alert(db, "Wallet Metrics Failed", str(exc), {"job": "recalculate_wallet_metrics"})
    finally:
        db.close()


def _quality_job() -> None:
    db = SessionLocal()
    try:
        run_with_task_lock(db, "signal_performance_update", lambda: update_signal_performance(db))
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="scheduler",
            message="Signal quality job failed",
            payload={"error": str(exc)},
        )
        send_ops_alert(db, "Signal Quality Failed", str(exc), {"job": "update_signal_performance"})
    finally:
        db.close()


def _daily_report_job() -> None:
    db = SessionLocal()
    try:
        run_with_task_lock(db, "daily_report", lambda: generate_daily_report(db))
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="scheduler",
            message="Daily report job failed",
            payload={"error": str(exc)},
        )
        send_ops_alert(db, "Daily Report Failed", str(exc), {"job": "generate_daily_report"})
    finally:
        db.close()


def _discovery_job() -> None:
    db = SessionLocal()
    try:
        if get_settings().discovery_enabled:
            run_with_task_lock(db, "discovery_run", lambda: run_wallet_discovery(db))
    except Exception as exc:
        write_log(
            db,
            level="error",
            module="scheduler",
            message="Wallet discovery job failed",
            payload={"error": str(exc)},
        )
        send_ops_alert(db, "Discovery Failed", str(exc), {"job": "wallet_discovery"})
    finally:
        db.close()


def _paper_trade_update_job() -> None:
    db = SessionLocal()
    try:
        def task():
            signal_result = process_new_signals_for_paper_trading(db)
            mark_result = update_open_paper_trades(db)
            aggregation_sent = flush_signal_aggregation_notifications(db)
            payload = {"signals": signal_result, "marks": mark_result, "smart_money_aggregations_sent": aggregation_sent}
            write_log(db, level="info", module="paper_trading", message="Paper trade update completed", payload=payload)
            return payload

        run_with_task_lock(db, "paper_trade_update", task)
    except Exception as exc:
        write_log(db, level="error", module="scheduler", message="Paper trade update failed", payload={"error": str(exc)})
        send_ops_alert(db, "Paper Trading Abnormal PnL", str(exc), {"job": "paper_trade_update"})
    finally:
        db.close()


def _health_report_job() -> None:
    db = SessionLocal()
    try:
        from app.services.health_service import system_health

        health = run_with_task_lock(db, "health_report", lambda: system_health(db))
        if isinstance(health, dict) and health.get("overall_status") in {"warning", "critical"}:
            send_ops_alert(db, "Health Report Warning", health.get("overall_status", "warning"), {"health": health.get("overall_status")})
    except Exception as exc:
        write_log(db, level="error", module="scheduler", message="Health report failed", payload={"error": str(exc)})
        send_ops_alert(db, "Database Error", str(exc), {"job": "health_report"})
    finally:
        db.close()


def _v2_equity_snapshot_job() -> None:
    db = SessionLocal()
    try:
        run_with_task_lock(db, "v2_equity_snapshot", lambda: record_equity_snapshot(db))
    except Exception as exc:
        write_log(db, level="error", module="v2_validation", message="Equity snapshot failed", payload={"error": str(exc)})
    finally:
        db.close()


def _shadow_trade_job() -> None:
    db = SessionLocal()
    try:
        def task():
            result = process_new_signals_for_shadow(db)
            result["marked"] = update_shadow_positions(db)
            return result

        result = run_with_task_lock(db, "v2_shadow_trade_processor", task)
        if result and result.get("processed"):
            write_log(db, level="info", module="v2_shadow", message="Shadow trade processing completed", payload=result)
    except Exception as exc:
        write_log(db, level="error", module="v2_shadow", message="Shadow trade processing failed", payload={"error": str(exc)})
    finally:
        db.close()
