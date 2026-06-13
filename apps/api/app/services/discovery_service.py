from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.wallet import Wallet
from app.services.hyperliquid_client import HyperliquidApiClient
from app.services.system_log_service import write_log


ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
ADDRESS_SCAN_RE = re.compile(r"0x[a-fA-F0-9]{40}")


def run_wallet_discovery(db: Session) -> dict[str, Any]:
    settings = get_settings()
    run = DiscoveryRun(status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        import_result = import_from_configured_sources(db)
        run.source_count = import_result["total_count"]
        run.scanned_count = import_result["valid_count"]
        discovered = import_result["inserted_count"]
        evaluated = evaluate_candidates(db)
        auto_added = auto_add_recommended_candidates(db) if settings.discovery_auto_add_enabled else 0
        run.discovered_count = discovered
        run.evaluated_count = evaluated
        run.recommended_count = db.query(DiscoveryCandidate).filter(DiscoveryCandidate.status == "recommended").count()
        run.failed_count = db.query(DiscoveryCandidate).filter(DiscoveryCandidate.status == "failed").count()
        run.no_activity_count = db.query(DiscoveryCandidate).filter(DiscoveryCandidate.status == "no_activity").count()
        run.auto_added_count = auto_added
        run.status = "ok"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        write_log(
            db,
            level="info",
            module="discovery",
            message="Wallet discovery completed",
            payload={**import_result, "evaluated": evaluated, "auto_added": auto_added},
        )
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        write_log(db, level="error", module="discovery", message="Wallet discovery failed", payload={"error": str(exc)})
    return discovery_summary(db)


def discover_candidate_addresses() -> dict[str, str]:
    settings = get_settings()
    results: dict[str, str] = {}
    for url in [item.strip() for item in settings.discovery_source_urls.split(",") if item.strip()]:
        try:
            response = httpx.get(url, timeout=20)
            response.raise_for_status()
            for address in ADDRESS_SCAN_RE.findall(response.text):
                results[address.lower()] = url
        except Exception:
            continue

    local_path = settings.discovery_local_source_path
    if local_path and os.path.exists(local_path):
        with open(local_path, "r", encoding="utf-8") as handle:
            for address in ADDRESS_SCAN_RE.findall(handle.read()):
                results[address.lower()] = local_path

    return results


def import_from_configured_sources(db: Session) -> dict[str, int]:
    return import_candidates(db, discover_candidate_addresses())


def import_candidates(db: Session, addresses_by_source: dict[str, str]) -> dict[str, int]:
    return _import_candidate_items(db, list(addresses_by_source.items()))


def _import_candidate_items(db: Session, items: list[tuple[str, str]]) -> dict[str, int]:
    stats = {"total_count": len(items), "valid_count": 0, "invalid_count": 0, "duplicate_count": 0, "inserted_count": 0}
    seen: set[str] = set()
    existing_candidates = {item.address.lower() for item in db.query(DiscoveryCandidate).all()}
    existing_wallets = {wallet.address.lower() for wallet in db.query(Wallet).filter(Wallet.status != "deleted").all()}
    for raw_address, source in items:
        address = str(raw_address).strip().lower()
        if not ADDRESS_RE.match(address):
            stats["invalid_count"] += 1
            continue
        stats["valid_count"] += 1
        if address in seen or address in existing_candidates or address in existing_wallets:
            stats["duplicate_count"] += 1
            continue
        seen.add(address)
        db.add(DiscoveryCandidate(address=address, source=source, status="pending"))
        try:
            db.commit()
            existing_candidates.add(address)
            stats["inserted_count"] += 1
        except IntegrityError:
            db.rollback()
            stats["duplicate_count"] += 1
    return stats


def import_candidates_from_text(db: Session, content: str, source: str = "paste") -> dict[str, int]:
    items = [(address.lower(), source) for address in ADDRESS_SCAN_RE.findall(content or "")]
    invalid_tokens = _invalid_address_tokens(content or "")
    stats = _import_candidate_items(db, items)
    stats["total_count"] += len(invalid_tokens)
    stats["invalid_count"] += len(invalid_tokens)
    return stats


def import_candidates_from_csv(db: Session, content: str, source: str = "csv") -> dict[str, int]:
    addresses: dict[str, str] = {}
    invalid = 0
    reader = csv.DictReader(io.StringIO(content or ""))
    if reader.fieldnames:
        address_field = next((name for name in reader.fieldnames if name.lower() in {"address", "wallet", "user"}), reader.fieldnames[0])
        for row in reader:
            value = str(row.get(address_field, "")).strip()
            if ADDRESS_RE.match(value):
                addresses[value.lower()] = source
            elif value:
                invalid += 1
    else:
        for row in csv.reader(io.StringIO(content or "")):
            for value in row:
                value = value.strip()
                if ADDRESS_RE.match(value):
                    addresses[value.lower()] = source
                elif value:
                    invalid += 1
    stats = import_candidates(db, addresses)
    stats["total_count"] += invalid
    stats["invalid_count"] += invalid
    return stats


def upsert_candidates(db: Session, addresses_by_source: dict[str, str]) -> int:
    return import_candidates(db, addresses_by_source)["inserted_count"]


def evaluate_candidates(db: Session, limit: int = 50) -> int:
    candidates = (
        db.query(DiscoveryCandidate)
        .filter(DiscoveryCandidate.status.in_(["pending", "candidate", "evaluated", "recommended", "no_activity", "failed"]))
        .order_by(DiscoveryCandidate.evaluated_at.asc().nullsfirst(), DiscoveryCandidate.discovered_at.asc())
        .limit(limit)
        .all()
    )
    client = HyperliquidApiClient(db)
    now = datetime.now(timezone.utc)
    start_ms = int((now - timedelta(days=30)).timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    evaluated = 0
    for candidate in candidates:
        try:
            fills = _with_backoff(lambda: client.get_user_fills(candidate.address))
            fills_by_time = _with_backoff(lambda: client.get_user_fills_by_time(candidate.address, start_ms, end_ms))
            state = _with_backoff(lambda: client.get_clearinghouse_state(candidate.address))
            orders = _with_backoff(lambda: client.get_open_orders(candidate.address))
            metrics = _score_candidate(candidate.address, fills_by_time or fills, state, orders)
            for key, value in metrics.items():
                setattr(candidate, key, value)
            if candidate.total_trades <= 0 and candidate.active_positions <= 0:
                candidate.status = "no_activity"
                candidate.failure_reason = "no_activity"
            else:
                candidate.status = "recommended" if candidate.recommendation == "recommend_add" else "evaluated"
                candidate.failure_reason = ""
            candidate.evaluated_at = now
            candidate.raw_json = json.dumps({"sample_fills": (fills_by_time or fills)[:20], "state": state, "orders": orders[:20]}, ensure_ascii=False)
            db.commit()
            evaluated += 1
        except Exception as exc:
            candidate.status = "failed"
            candidate.failure_reason = _failure_reason(exc)
            candidate.reason = str(exc)[:500]
            candidate.evaluated_at = now
            db.commit()
    return evaluated


def auto_add_recommended_candidates(db: Session) -> int:
    if not get_settings().discovery_auto_add_enabled:
        return 0
    return approve_recommended_candidates(db, limit=20)


def approve_candidate(db: Session, candidate_id: int) -> Wallet:
    candidate = db.get(DiscoveryCandidate, candidate_id)
    if not candidate:
        raise ValueError("Discovery candidate not found")
    if candidate.status not in {"recommended", "evaluated"}:
        raise ValueError("Only evaluated or recommended candidates can be approved")
    return _candidate_to_wallet(db, candidate)


def approve_recommended_candidates(db: Session, limit: int = 20) -> int:
    threshold = get_settings().discovery_min_score_to_add
    candidates = (
        db.query(DiscoveryCandidate)
        .filter(
            DiscoveryCandidate.status == "recommended",
            DiscoveryCandidate.score >= threshold,
            DiscoveryCandidate.added_wallet_id.is_(None),
        )
        .order_by(DiscoveryCandidate.score.desc())
        .limit(20)
        .all()
    )
    added = 0
    for candidate in candidates:
        _candidate_to_wallet(db, candidate)
        added += 1
    return added


def _candidate_to_wallet(db: Session, candidate: DiscoveryCandidate) -> Wallet:
    existing = {wallet.address.lower(): wallet.id for wallet in db.query(Wallet).filter(Wallet.status != "deleted").all()}
    if candidate.address.lower() in existing:
        wallet = db.get(Wallet, existing[candidate.address.lower()])
        candidate.added_wallet_id = existing[candidate.address.lower()]
        candidate.status = "approved"
        db.commit()
        return wallet
    wallet = Wallet(
        address=candidate.address,
        platform="hyperliquid",
        name=f"Discovered {candidate.address[:6]}...{candidate.address[-4:]}",
        tags="auto-discovered,manual-approved",
        manual_score=max(1, min(100, candidate.score)),
        status="active",
        notes=f"Approved from Discovery Engine. Estimated ROI {candidate.roi:.2f}%, estimated PnL {candidate.total_pnl:.2f}.",
    )
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    candidate.added_wallet_id = wallet.id
    candidate.status = "approved"
    db.commit()
    return wallet


def discovery_summary(db: Session) -> dict[str, Any]:
    candidates = db.query(DiscoveryCandidate).all()
    runs = db.query(DiscoveryRun).order_by(DiscoveryRun.started_at.desc()).limit(10).all()
    return {
        "total_candidates": len(candidates),
        "recommended": len([item for item in candidates if item.status == "recommended"]),
        "added": len([item for item in candidates if item.status == "added"]),
        "approved": len([item for item in candidates if item.status == "approved"]),
        "failed": len([item for item in candidates if item.status == "failed"]),
        "no_activity": len([item for item in candidates if item.status == "no_activity"]),
        "top_candidates": [candidate_to_dict(item) for item in sorted(candidates, key=lambda c: c.score, reverse=True)[:25]],
        "recent_runs": [run_to_dict(run) for run in runs],
    }


def candidate_to_dict(candidate: DiscoveryCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "address": candidate.address,
        "platform": candidate.platform,
        "source": candidate.source,
        "status": candidate.status,
        "score": candidate.score,
        "roi": candidate.roi,
        "realized_pnl": candidate.realized_pnl,
        "unrealized_pnl": candidate.unrealized_pnl,
        "total_pnl": candidate.total_pnl,
        "total_trades": candidate.total_trades,
        "trades_7d": candidate.trades_7d,
        "trades_30d": candidate.trades_30d,
        "win_rate": candidate.win_rate,
        "profit_factor": candidate.profit_factor,
        "gross_profit": candidate.gross_profit,
        "avg_leverage": candidate.avg_leverage,
        "max_drawdown": candidate.max_drawdown,
        "risk_score": candidate.risk_score,
        "grade": candidate.grade,
        "aggregation_confidence": candidate.aggregation_confidence,
        "metrics_estimated": candidate.metrics_estimated,
        "funding_included": candidate.funding_included,
        "drawdown_estimation_method": candidate.drawdown_estimation_method,
        "hard_filter_pass": candidate.hard_filter_pass,
        "soft_watch_eligible": candidate.soft_watch_eligible,
        "failed_reasons": candidate.failed_reasons,
        "account_value": candidate.account_value,
        "active_positions": candidate.active_positions,
        "best_symbol": candidate.best_symbol,
        "worst_symbol": candidate.worst_symbol,
        "recommendation": candidate.recommendation,
        "reason": candidate.reason,
        "failure_reason": candidate.failure_reason,
        "added_wallet_id": candidate.added_wallet_id,
        "discovered_at": candidate.discovered_at,
        "evaluated_at": candidate.evaluated_at,
    }


def run_to_dict(run: DiscoveryRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "source_count": run.source_count,
        "scanned_count": run.scanned_count,
        "discovered_count": run.discovered_count,
        "evaluated_count": run.evaluated_count,
        "recommended_count": run.recommended_count,
        "failed_count": run.failed_count,
        "no_activity_count": run.no_activity_count,
        "auto_added_count": run.auto_added_count,
        "error_message": run.error_message,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def _score_candidate(address: str, fills: list[dict[str, Any]], state: dict[str, Any], orders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    pnl_values = [_to_float(fill.get("closedPnl")) for fill in fills if _to_float(fill.get("closedPnl")) != 0]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    gross_profit = sum(wins)
    realized = sum(_to_float(fill.get("closedPnl")) for fill in fills)
    positions = state.get("assetPositions", [])
    unrealized = sum(_to_float(item.get("position", {}).get("unrealizedPnl")) for item in positions)
    account_value = _to_float(state.get("marginSummary", {}).get("accountValue"))
    total_pnl = realized + unrealized
    base_capital = max(account_value - total_pnl, 1)
    roi = total_pnl / base_capital * 100
    win_rate = len(wins) / len(pnl_values) * 100 if pnl_values else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses else (sum(wins) if wins else 0)
    max_drawdown = _max_drawdown(pnl_values)
    trades_7d = len([fill for fill in fills if _fill_time(fill) >= now - timedelta(days=7)])
    leverages = [_position_leverage(item.get("position", {})) for item in positions]
    avg_leverage = sum(leverages) / len(leverages) if leverages else 0
    symbol_pnl = defaultdict(float)
    for fill in fills:
        symbol_pnl[str(fill.get("coin", ""))] += _to_float(fill.get("closedPnl"))
    best_symbol = max(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else ""
    worst_symbol = min(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else ""
    max_single_loss_pct = abs(min(losses)) / max(gross_profit, 1) if losses else 0
    aggregation_confidence = "high" if len(fills) >= get_settings().smart_min_trade_count_30d and account_value > 0 else "low"
    risk_score = _candidate_risk(avg_leverage, max_drawdown, win_rate, len(orders or []), roi)
    raw_score = _candidate_score(len(fills), trades_7d, win_rate, profit_factor, roi, total_pnl, len(positions), risk_score)
    filters = _smart_money_filters(
        trade_count_30d=len(fills),
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_single_loss_pct=max_single_loss_pct,
        gross_profit=gross_profit,
        realized_pnl=realized,
        aggregation_confidence=aggregation_confidence,
        metrics_estimated=True,
        funding_included=False,
        drawdown_estimation_method="current_account_value",
    )
    score = min(raw_score, 84) if filters["soft_watch_eligible"] else raw_score
    grade = _candidate_grade(score, risk_score)
    if filters["soft_watch_eligible"]:
        grade = "B" if score >= 65 else "Watch"
    if not filters["hard_filter_pass"] and not filters["soft_watch_eligible"]:
        grade = "Reject"
    recommendation = (
        "recommend_add"
        if score >= get_settings().discovery_min_score_to_add
        and grade in {"S", "A"}
        and filters["hard_filter_pass"]
        and not filters["soft_watch_eligible"]
        else "watch"
    )
    reason = f"Estimated: trades={len(fills)}, win_rate={win_rate:.1f}%, pf={profit_factor:.2f}, roi={roi:.2f}%, pnl={total_pnl:.2f}, risk={risk_score}"
    return {
        "score": score,
        "roi": round(roi, 4),
        "realized_pnl": round(realized, 6),
        "unrealized_pnl": round(unrealized, 6),
        "total_pnl": round(total_pnl, 6),
        "total_trades": len(fills),
        "trades_7d": trades_7d,
        "trades_30d": len(fills),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 4),
        "gross_profit": round(gross_profit, 6),
        "avg_leverage": round(avg_leverage, 4),
        "max_drawdown": round(max_drawdown, 4),
        "risk_score": risk_score,
        "grade": grade,
        "aggregation_confidence": aggregation_confidence,
        "metrics_estimated": 1,
        "funding_included": 0,
        "drawdown_estimation_method": "current_account_value",
        "hard_filter_pass": 1 if filters["hard_filter_pass"] else 0,
        "soft_watch_eligible": 1 if filters["soft_watch_eligible"] else 0,
        "failed_reasons": json.dumps(filters["failed_reasons"]),
        "account_value": round(account_value, 6),
        "active_positions": len(positions),
        "best_symbol": best_symbol,
        "worst_symbol": worst_symbol,
        "recommendation": recommendation,
        "reason": reason,
    }


def _candidate_score(total_trades: int, trades_7d: int, win_rate: float, profit_factor: float, roi: float, pnl: float, positions: int, risk_score: int = 0) -> int:
    score = 0
    score += min(total_trades, 80) * 0.25
    score += min(trades_7d, 30) * 0.6
    score += min(win_rate, 80) * 0.35
    score += min(profit_factor * 12, 20)
    score += max(min(roi, 50), -50) * 0.25
    score += 10 if pnl > 0 else 0
    score += min(positions, 5)
    score -= min(risk_score, 100) * 0.15
    return max(1, min(100, round(score)))


def _candidate_risk(avg_leverage: float, max_drawdown: float, win_rate: float, open_orders: int, roi: float) -> int:
    score = 0
    score += min(avg_leverage * 6, 45)
    score += min(abs(max_drawdown) * 1.2, 30)
    score += max(0, 50 - win_rate) * 0.4
    score += min(open_orders * 2, 10)
    score += 10 if roi < 0 else 0
    return max(1, min(100, round(score)))


def _candidate_grade(score: int, risk_score: int) -> str:
    if score >= 90 and risk_score <= 45:
        return "S"
    if score >= 80 and risk_score <= 60:
        return "A"
    if score >= 65:
        return "B"
    if score >= 45:
        return "Watch"
    return "Reject"


def _smart_money_filters(
    *,
    trade_count_30d: int,
    win_rate: float,
    profit_factor: float,
    max_single_loss_pct: float,
    gross_profit: float,
    realized_pnl: float,
    aggregation_confidence: str,
    metrics_estimated: bool,
    funding_included: bool,
    drawdown_estimation_method: str,
) -> dict[str, Any]:
    settings = get_settings()
    min_win_rate = settings.smart_min_win_rate * 100 if settings.smart_min_win_rate <= 1 else settings.smart_min_win_rate
    failed = []
    if trade_count_30d < settings.smart_min_trade_count_30d:
        failed.append("trade_count_30d_below_threshold")
    if win_rate < min_win_rate:
        failed.append("win_rate_below_threshold")
    if profit_factor < settings.smart_min_profit_factor:
        failed.append("profit_factor_below_threshold")
    if max_single_loss_pct > settings.smart_max_single_loss_pct:
        failed.append("max_single_loss_pct_above_threshold")
    soft_risk = (
        aggregation_confidence == "low"
        or metrics_estimated
        or not funding_included
        or drawdown_estimation_method == "current_account_value"
    )
    soft_watch = (
        soft_risk
        and trade_count_30d >= settings.smart_soft_watch_min_trade_count_30d
        and gross_profit >= settings.smart_soft_watch_min_gross_profit
        and realized_pnl > 0
    )
    if soft_risk:
        failed.append("estimated_metrics_soft_filter")
    return {
        "hard_filter_pass": len([item for item in failed if item != "estimated_metrics_soft_filter"]) == 0,
        "soft_watch_eligible": soft_watch,
        "failed_reasons": failed,
    }


def _max_drawdown(pnl_values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for pnl in pnl_values:
        equity += pnl
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def _position_leverage(position: dict[str, Any]) -> float:
    leverage = position.get("leverage")
    if isinstance(leverage, dict):
        return _to_float(leverage.get("value"))
    return _to_float(leverage)


def _with_backoff(callable_fn, attempts: int = 2):
    last_error = None
    for attempt in range(attempts):
        try:
            return callable_fn()
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise last_error


def _failure_reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "429" in message or "rate" in message:
        return "rate_limit"
    if "invalid" in message:
        return "invalid_wallet"
    return "api_error"


def _invalid_address_tokens(content: str) -> list[str]:
    tokens = re.findall(r"0x[0-9a-zA-Z]+", content)
    return [token for token in tokens if not ADDRESS_RE.match(token)]


def _fill_time(fill: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(fill.get("time", 0)) / 1000, tz=timezone.utc)


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
