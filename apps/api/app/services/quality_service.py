import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.models.market_data import WalletMetric
from app.models.signal import DailyReport, PaperTrade, RiskRule, Signal, SignalPerformance
from app.models.wallet import Wallet
from app.services.hyperliquid_client import HyperliquidApiClient
from app.services.system_log_service import write_log
from app.services.telegram_service import send_daily_report_notification


WINDOWS = [
    ("return_5m", timedelta(minutes=5)),
    ("return_15m", timedelta(minutes=15)),
    ("return_1h", timedelta(hours=1)),
    ("return_4h", timedelta(hours=4)),
    ("return_24h", timedelta(hours=24)),
]


def get_or_create_risk_rule(db: Session) -> RiskRule:
    rule = db.query(RiskRule).order_by(RiskRule.id.asc()).first()
    if rule:
        return rule
    rule = RiskRule()
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_signal_performance(db: Session, mids: Optional[Dict[str, str]] = None) -> int:
    mids = mids if mids is not None else HyperliquidApiClient(db).get_all_mids()
    signals = db.query(Signal).filter(Signal.current_price > 0).all()
    now = datetime.now(timezone.utc)
    updated = 0
    for signal in signals:
        price = _to_float(mids.get(signal.symbol))
        if price <= 0:
            continue
        perf = db.query(SignalPerformance).filter(SignalPerformance.signal_id == signal.id).first()
        if not perf:
            perf = SignalPerformance(
                signal_id=signal.id,
                wallet_id=signal.wallet_id,
                symbol=signal.symbol,
                side=signal.side,
                entry_price=signal.current_price or signal.source_entry_price,
            )
            db.add(perf)
        ret = _return_pct(signal.side, perf.entry_price, price)
        perf.max_favorable = max(perf.max_favorable or 0, ret)
        perf.max_adverse = min(perf.max_adverse or 0, ret)
        perf.hit_stop_loss = 1 if perf.max_adverse <= -3 else (perf.hit_stop_loss or 0)
        perf.hit_take_profit = 1 if perf.max_favorable >= 6 else (perf.hit_take_profit or 0)
        perf.sample_count = (perf.sample_count or 0) + 1
        perf.last_price = price
        perf.last_evaluated_at = now
        age = now - _as_utc(signal.created_at)
        for field, delta in WINDOWS:
            if age >= delta and getattr(perf, field) == 0:
                setattr(perf, field, ret)
        db.commit()
        updated += 1
    if updated:
        write_log(db, level="info", module="quality", message="Signal performance updated", payload={"signals": updated})
    return updated


def wallet_contributions(db: Session) -> list[dict[str, Any]]:
    wallets = db.query(Wallet).filter(Wallet.status != "deleted").all()
    rows = []
    for wallet in wallets:
        signals = db.query(Signal).filter(Signal.wallet_id == wallet.id).all()
        trades = db.query(PaperTrade).filter(PaperTrade.wallet_id == wallet.id).all()
        closed = [trade for trade in trades if trade.status == "closed"]
        pnl = sum(trade.pnl for trade in trades)
        wins = [trade for trade in closed if trade.pnl > 0]
        symbol_pnl = defaultdict(float)
        for trade in trades:
            symbol_pnl[trade.symbol] += trade.pnl
        best_symbol = max(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else None
        worst_symbol = min(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else None
        win_rate = (len(wins) / len(closed) * 100) if closed else 0
        max_dd = _max_drawdown(closed)
        grade = _wallet_grade(wallet, len(signals), pnl, win_rate, max_dd)
        rows.append(
            {
                "wallet_id": wallet.id,
                "wallet_name": wallet.name,
                "signal_count": len(signals),
                "simulated_pnl": round(pnl, 6),
                "win_rate": round(win_rate, 2),
                "max_drawdown": max_dd,
                "best_symbol": best_symbol,
                "worst_symbol": worst_symbol,
                "grade": grade,
                "keep_recommendation": "keep" if grade in {"S", "A", "B"} else "remove",
            }
        )
    return sorted(rows, key=lambda item: (item["simulated_pnl"], item["win_rate"]), reverse=True)


def signal_type_analysis(db: Session) -> list[dict[str, Any]]:
    rows = []
    for signal_type in ["open", "add", "reduce", "close"]:
        signals = db.query(Signal).filter(Signal.signal_type == signal_type).all()
        signal_ids = [signal.id for signal in signals]
        perfs = db.query(SignalPerformance).filter(SignalPerformance.signal_id.in_(signal_ids)).all() if signal_ids else []
        returns = [_effective_return(perf) for perf in perfs]
        wins = [value for value in returns if value > 0]
        rows.append(
            {
                "signal_type": signal_type,
                "signal_count": len(signals),
                "avg_return_24h": round(sum(returns) / len(returns), 4) if returns else 0,
                "win_rate_24h": round(len(wins) / len(returns) * 100, 2) if returns else 0,
                "avg_max_favorable": round(_avg([perf.max_favorable for perf in perfs]), 4),
                "avg_max_adverse": round(_avg([perf.max_adverse for perf in perfs]), 4),
            }
        )
    return rows


def quality_dashboard(db: Session) -> dict[str, Any]:
    contributions = wallet_contributions(db)
    type_rows = signal_type_analysis(db)
    closed = db.query(PaperTrade).filter(PaperTrade.status == "closed").all()
    wins = [trade for trade in closed if trade.pnl > 0]
    max_dd = _max_drawdown(closed)
    signal_win_rate = round(len(wins) / len(closed) * 100, 2) if closed else 0
    recommendation = _live_test_recommendation(contributions, signal_win_rate, max_dd)
    return {
        "seven_day_curve": seven_day_curve(db),
        "wallet_rankings": contributions,
        "signal_type_analysis": type_rows,
        "signal_win_rate": signal_win_rate,
        "max_drawdown": max_dd,
        "system_status": "ready_for_inner_test" if contributions else "collecting_data",
        "live_test_recommendation": recommendation,
    }


def seven_day_curve(db: Session) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    rows = []
    cumulative = 0.0
    closed = db.query(PaperTrade).filter(PaperTrade.status == "closed").all()
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        day_pnl = sum(
            trade.pnl
            for trade in closed
            if trade.closed_at and _as_utc(trade.closed_at).date() == day
        )
        cumulative += day_pnl
        rows.append({"date": day.isoformat(), "pnl": round(day_pnl, 6), "cumulative_pnl": round(cumulative, 6)})
    return rows


def generate_daily_report(db: Session, report_date: Optional[str] = None, send_telegram: bool = True) -> DailyReport:
    day = report_date or datetime.now(timezone.utc).date().isoformat()
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    signals = db.query(Signal).filter(Signal.created_at >= start, Signal.created_at < end).all()
    closed = db.query(PaperTrade).filter(PaperTrade.closed_at >= start, PaperTrade.closed_at < end).all()
    pnl = sum(trade.pnl for trade in closed)
    contributions = wallet_contributions(db)
    keep = [item["wallet_name"] for item in contributions if item["keep_recommendation"] == "keep"][:5]
    remove = [item["wallet_name"] for item in contributions if item["keep_recommendation"] == "remove"][:5]
    best_wallet = contributions[0]["wallet_name"] if contributions else ""
    worst_wallet = contributions[-1]["wallet_name"] if contributions else ""
    type_rows = signal_type_analysis(db)
    focus = _tomorrow_focus(contributions, type_rows)
    recommendation = quality_dashboard(db)["live_test_recommendation"]
    payload = {
        "signal_types": type_rows,
        "wallet_rankings": contributions[:10],
        "focus": focus,
    }
    report = db.query(DailyReport).filter(DailyReport.report_date == day).first()
    if not report:
        report = DailyReport(report_date=day)
        db.add(report)
    report.signal_count = len(signals)
    report.simulated_pnl = round(pnl, 6)
    report.best_wallet = best_wallet
    report.worst_wallet = worst_wallet
    report.keep_wallets_json = json.dumps(keep, ensure_ascii=False)
    report.remove_wallets_json = json.dumps(remove, ensure_ascii=False)
    report.focus_json = json.dumps(focus, ensure_ascii=False)
    report.live_test_recommendation = recommendation
    report.payload_json = json.dumps(payload, ensure_ascii=False)
    db.commit()
    db.refresh(report)
    if send_telegram:
        send_daily_report_notification(db, report)
    return report


def risk_rule_to_dict(rule: RiskRule) -> dict[str, Any]:
    return {
        "blacklist_wallets": json.loads(rule.blacklist_wallets or "[]"),
        "whitelist_wallets": json.loads(rule.whitelist_wallets or "[]"),
        "blacklist_symbols": json.loads(rule.blacklist_symbols or "[]"),
        "min_wallet_score": rule.min_wallet_score,
        "max_allowed_leverage": rule.max_allowed_leverage,
        "min_trades": rule.min_trades,
        "min_30d_win_rate": rule.min_30d_win_rate,
        "only_grade_a_or_s": bool(rule.only_grade_a_or_s),
    }


def report_to_dict(report: DailyReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "report_date": report.report_date,
        "signal_count": report.signal_count,
        "simulated_pnl": report.simulated_pnl,
        "best_wallet": report.best_wallet,
        "worst_wallet": report.worst_wallet,
        "keep_wallets": json.loads(report.keep_wallets_json or "[]"),
        "remove_wallets": json.loads(report.remove_wallets_json or "[]"),
        "focus": json.loads(report.focus_json or "[]"),
        "live_test_recommendation": report.live_test_recommendation,
        "payload": json.loads(report.payload_json or "{}"),
        "created_at": report.created_at,
    }


def _return_pct(side: str, entry: float, price: float) -> float:
    if entry <= 0:
        return 0.0
    direction = -1 if side == "short" else 1
    return round((price - entry) / entry * 100 * direction, 6)


def _effective_return(perf: SignalPerformance) -> float:
    for field in ["return_24h", "return_4h", "return_1h", "return_15m", "return_5m"]:
        value = getattr(perf, field)
        if value != 0:
            return value
    return _return_pct(perf.side, perf.entry_price, perf.last_price)


def _wallet_grade(wallet: Wallet, signal_count: int, pnl: float, win_rate: float, max_dd: float) -> str:
    score = wallet.manual_score * 0.45 + min(signal_count, 40) * 0.4 + max(min(pnl, 100), -100) * 0.12 + win_rate * 0.25 - max_dd * 0.4
    if score >= 85:
        return "S"
    if score >= 72:
        return "A"
    if score >= 58:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _live_test_recommendation(contributions: list[dict[str, Any]], signal_win_rate: float, max_dd: float) -> str:
    top = contributions[0] if contributions else None
    if not top:
        return "Not recommended: collect at least 7 days of signal data first."
    if top["grade"] in {"S", "A"} and signal_win_rate >= 55 and max_dd <= 8 and top["simulated_pnl"] > 0:
        return "Watchlist only: consider manual review for tiny live test after 7 full days. Automation remains disabled."
    return "Not recommended: keep paper testing until wallet quality is stronger."


def _tomorrow_focus(contributions: list[dict[str, Any]], type_rows: list[dict[str, Any]]) -> list[str]:
    focus = []
    if contributions:
        focus.append(f"Focus on top wallet: {contributions[0]['wallet_name']}")
    best_type = max(type_rows, key=lambda item: item["avg_return_24h"]) if type_rows else None
    if best_type and best_type["signal_count"]:
        focus.append(f"Prioritize {best_type['signal_type']} signals")
    focus.append("Continue paper-only validation; no private keys or live orders.")
    return focus


def _max_drawdown(closed: Iterable[PaperTrade]) -> float:
    equity = 1000.0
    peak = 1000.0
    max_dd = 0.0
    for trade in sorted(closed, key=lambda item: item.closed_at or item.opened_at):
        equity += trade.pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)
    return round(max_dd, 2)


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
