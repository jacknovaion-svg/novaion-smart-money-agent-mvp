"""Read-only V3 reporting, separated from the legacy Paper/V2 equity curves."""

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from app.models.wallet import Wallet
from app.models.signal import Signal
from app.models.market_data import WalletPositionSnapshot
from app.models.v3 import (
    V3Run,
    V3Trade,
    V3Action,
    V3Position,
    V3Equity,
    V3Processing,
    V3WalletEvaluation,
    V3Lifecycle,
    V3Quality,
    V3Job,
)
from app.services.v3_shadow import account, now_utc, utc
from app.services.v3_intelligence import pnl_metrics


def drawdown(curve, max_gap_seconds=900):
    if len(curve) < 2:
        return dict(amount=None, percent=None, reason="insufficient_equity_samples")
    if any(r.quality != "GOOD" for r in curve) or any(
        (utc(b.captured_at) - utc(a.captured_at)).total_seconds() > max_gap_seconds
        for a, b in zip(curve, curve[1:])
    ):
        return dict(amount=None, percent=None, reason="incomplete_equity_curve")
    peak = curve[0].equity
    amount = percent = 0.0
    for r in curve:
        peak = max(peak, r.equity)
        amount = max(amount, peak - r.equity)
        if peak > 0:
            percent = max(percent, (peak - r.equity) / peak * 100)
    return dict(
        amount=amount,
        percent=percent,
        reason="",
        basis="observed_post_cutover_equity; between-sample moves unobserved",
    )


def trade_metrics(trades):
    closed = [t for t in trades if t.status == "closed"]
    m = pnl_metrics([t.net_pnl for t in closed])
    times = [(utc(t.closed_at) - utc(t.opened_at)).total_seconds() for t in closed]
    m.update(
        trades=len(trades),
        closed_trades=len(closed),
        gross_realized_pnl=sum(t.gross_pnl for t in trades),
        net_realized_pnl=sum(t.net_pnl for t in trades),
        fees=sum(t.fees for t in trades),
        slippage=sum(t.slippage for t in trades),
        funding=sum(t.funding for t in trades),
        funding_complete=all(t.funding_complete for t in trades) if trades else False,
        average_holding_seconds=statistics.mean(times) if times else None,
        median_holding_seconds=statistics.median(times) if times else None,
        max_drawdown=None,
        drawdown_reason="group_equity_not_sampled",
    )
    values = [t.net_pnl for t in closed]
    if len(values) >= 30:
        se = statistics.stdev(values) / math.sqrt(len(values))
        m["expectancy_approx_95_ci"] = [
            statistics.mean(values) - 1.96 * se,
            statistics.mean(values) + 1.96 * se,
        ]
    else:
        m["expectancy_approx_95_ci"] = None
    return m


def attribution(db, run):
    trades = db.query(V3Trade).filter_by(run_id=run.id).all()
    events = db.query(V3Processing).filter_by(run_id=run.id).all()
    signals = {
        s.id: s
        for s in db.query(Signal).filter(
            Signal.created_at > run.cutover_at, Signal.id > run.high_water_id
        )
    }
    result = {}
    for name, key in [
        ("wallet", lambda t: str(t.wallet_id)),
        ("symbol", lambda t: t.symbol),
        ("side", lambda t: t.side),
        ("tier", lambda t: json.loads(t.context_json).get("tier", "UNKNOWN")),
        (
            "regime",
            lambda t: json.loads(t.context_json)
            .get("regime", {})
            .get("trend", "UNKNOWN"),
        ),
        (
            "volatility",
            lambda t: json.loads(t.context_json)
            .get("regime", {})
            .get("volatility", "UNKNOWN"),
        ),
        (
            "signal_score",
            lambda t: str(
                int(json.loads(t.context_json).get("signal_score", 0) // 10) * 10
            )
            + "s",
        ),
        (
            "copyability",
            lambda t: str(
                int(json.loads(t.context_json).get("copyability", 0) // 10) * 10
            )
            + "s",
        ),
        (
            "holding_time",
            lambda t: (
                "OPEN"
                if not t.closed_at
                else (
                    "<1h"
                    if (t.closed_at - t.opened_at).total_seconds() < 3600
                    else (
                        "1h-24h"
                        if (t.closed_at - t.opened_at).total_seconds() < 86400
                        else ">24h"
                    )
                )
            ),
        ),
    ]:
        groups = defaultdict(list)
        for t in trades:
            groups[key(t)].append(t)
        if name == "wallet":
            for (wid,) in db.query(Wallet.id).filter_by(status="active"):
                groups.setdefault(str(wid), [])
        rows = []
        for k, group in groups.items():
            signal_count = (
                sum(1 for s in signals.values() if str(s.wallet_id) == k)
                if name == "wallet"
                else (
                    sum(s.symbol == k for s in signals.values())
                    if name == "symbol"
                    else None
                )
            )
            rows.append(
                dict(
                    key=k,
                    signals=signal_count,
                    conversion_rate=len(group) / signal_count if signal_count else None,
                    **trade_metrics(group)
                )
            )
        result[name] = sorted(rows, key=lambda r: r["net_realized_pnl"], reverse=True)
    action_groups = defaultdict(list)
    for a in db.query(V3Action).filter_by(run_id=run.id):
        action_groups[a.action].append(a)
    result["action"] = [
        dict(
            action=k,
            count=len(v),
            gross_pnl=sum(a.gross_pnl for a in v),
            fees=sum(a.fees for a in v),
            slippage=sum(a.slippage for a in v),
            funding=sum(a.funding for a in v),
            net_pnl=sum(a.net_pnl for a in v),
            attribution_basis="cashflow booked by action; not causal predictive alpha",
        )
        for k, v in action_groups.items()
    ]
    result["summary"] = trade_metrics(trades)
    result["entry_action"] = entry_attribution(db, run, trades)
    result["rolling"] = {
        str(days)
        + "d": trade_metrics(
            [t for t in trades if t.opened_at >= now_utc() - timedelta(days=days)]
        )
        for days in (7, 30, 90)
    }
    result["rolling"]["lifetime"] = trade_metrics(trades)
    quality_events = (
        db.query(V3Quality).filter(V3Quality.created_at >= run.cutover_at).all()
    )
    contaminated = []
    clean = []
    for t in trades:
        affected = any(
            q.wallet_id in {None, t.wallet_id}
            and (not q.symbol or q.symbol == t.symbol)
            and t.opened_at <= q.created_at <= (t.closed_at or now_utc())
            for q in quality_events
        )
        (contaminated if affected else clean).append(t)
    result["quality_cohorts"] = {
        "clean": trade_metrics(clean),
        "contaminated": trade_metrics(contaminated),
    }
    result["funnel"] = dict(
        signals=len(signals),
        consumed=len(events),
        processed=sum(e.processing_status == "processed" for e in events),
        ignored=dict(
            Counter(e.error for e in events if e.processing_status == "ignored")
        ),
        retry=sum(e.processing_status == "retry" for e in events),
        trades=len(trades),
    )
    cfg = json.loads(run.config_json)
    m = result["summary"]
    ci = m["expectancy_approx_95_ci"]
    result["validation"] = {
        "grade": (
            "INSUFFICIENT DATA"
            if m["closed_trades"] < cfg["v3_min_validation_closed"]
            else (
                "CONDITIONAL PASS"
                if ci and ci[0] > 0 and (m["profit_factor"] or 0) > 1
                else "FAIL"
            )
        ),
        "note": "Forward simulation only. Correlated trades, estimated funding and missing equity periods limit inference.",
    }
    return result


def entry_attribution(db, run, trades):
    """Pro-rata cost lots distinguish OPEN vs ADD contributions without changing average-cost execution."""
    groups = defaultdict(
        lambda: dict(
            lots=0, gross_pnl=0.0, fees=0.0, slippage=0.0, funding=0.0, net_pnl=0.0
        )
    )
    for t in trades:
        lots = []
        direction = 1 if t.side == "long" else -1
        actions = sorted(
            db.query(V3Action).filter_by(trade_id=t.id).all(),
            key=lambda a: (a.created_at, 0 if a.action == "FUNDING" else 1, a.id),
        )
        for a in actions:
            if a.action in {"OPEN", "ADD"}:
                lots.append(
                    dict(
                        kind=a.action, remaining=a.quantity, reference=a.reference_price
                    )
                )
                g = groups[a.action]
                g["lots"] += 1
                g["fees"] += a.fees
                g["slippage"] += a.slippage
                g["net_pnl"] += a.net_pnl
            else:
                total = sum(l["remaining"] for l in lots)
                if total <= 0:
                    continue
                for lot in lots:
                    weight = lot["remaining"] / total
                    g = groups[lot["kind"]]
                    gross = (
                        0.0
                        if a.action == "FUNDING"
                        else direction
                        * (a.reference_price - lot["reference"])
                        * a.quantity
                        * weight
                    )
                    fee = a.fees * weight
                    slip = a.slippage * weight
                    funding = a.funding * weight
                    g["gross_pnl"] += gross
                    g["fees"] += fee
                    g["slippage"] += slip
                    g["funding"] += funding
                    g["net_pnl"] += gross - fee - slip - funding
                    if a.action != "FUNDING":
                        lot["remaining"] = max(
                            0, lot["remaining"] - a.quantity * weight
                        )
    return [
        dict(
            entry_action=k,
            **v,
            basis="pro-rata entry lots, including immediately recognized entry costs"
        )
        for k, v in groups.items()
    ]


def dashboard(db):
    run = db.query(V3Run).order_by(V3Run.id.desc()).first()
    if not run:
        return dict(enabled=False)
    cfg = json.loads(run.config_json)
    curve = (
        db.query(V3Equity)
        .filter_by(run_id=run.id)
        .order_by(V3Equity.captured_at, V3Equity.id)
        .all()
    )
    ranked = []
    for w in db.query(Wallet).filter_by(status="active"):
        e = (
            db.query(V3WalletEvaluation)
            .filter_by(wallet_id=w.id)
            .order_by(V3WalletEvaluation.as_of.desc())
            .first()
        )
        life = (
            db.query(V3Lifecycle)
            .filter_by(wallet_id=w.id)
            .order_by(V3Lifecycle.id.desc())
            .first()
        )
        source = (
            db.query(WalletPositionSnapshot)
            .filter_by(wallet_id=w.id)
            .order_by(WalletPositionSnapshot.created_at.desc())
            .first()
        )
        freshness = (
            (now_utc() - utc(source.created_at)).total_seconds() if source else None
        )
        ranked.append(
            dict(
                wallet_id=w.id,
                address=w.address[:6] + "..." + w.address[-4:],
                score=e.score if e else None,
                tier=e.tier if e else "Pending",
                copyability=e.copyability if e else None,
                copy_label=e.copy_label if e else "Pending",
                quality=e.quality if e else "Pending",
                lifecycle=life.state if life else "Watchlist",
                freshness_seconds=freshness,
                data_quality=(
                    "BAD"
                    if freshness is None or freshness > 3600
                    else (
                        "DEGRADED"
                        if freshness > cfg["v3_sync_max_age_seconds"]
                        else "GOOD"
                    )
                ),
                as_of=e.as_of if e else None,
                metrics=json.loads(e.metrics_json) if e else {},
            )
        )
    positions = [
        {
            k: getattr(p, k)
            for k in (
                "id",
                "wallet_id",
                "symbol",
                "state",
                "quantity",
                "margin",
                "average_entry",
                "mark_price",
                "unrealized_pnl",
                "quality",
                "updated_at",
            )
        }
        for p in db.query(V3Position).filter(
            V3Position.run_id == run.id, V3Position.state != "FLAT"
        )
    ]
    recent = []
    for e in (
        db.query(V3Processing)
        .filter_by(run_id=run.id)
        .order_by(V3Processing.id.desc())
        .limit(30)
    ):
        s = db.get(Signal, e.signal_id)
        ev = json.loads(e.evaluation_json)
        recent.append(
            dict(
                id=s.id,
                wallet_id=s.wallet_id,
                symbol=s.symbol,
                side=ev.get("side"),
                action=e.action,
                status=e.processing_status,
                reason=e.error,
                score=ev.get("signal_score"),
                quality=ev.get("data_quality"),
                created_at=s.created_at,
                processed_at=e.processed_at,
            )
        )
    job = db.get(V3Job, "shadow_v3_cycle")
    status = "NOT_RUN" if not job else job.status
    if (
        job
        and job.finished_at
        and (now_utc() - utc(job.finished_at)).total_seconds() > 900
    ):
        status = "STALE"
    analysis = attribution(db, run)
    return dict(
        enabled=True,
        version=run.version,
        cutover_at=run.cutover_at,
        started_at=run.started_at,
        end_at=run.started_at + timedelta(days=30) if run.started_at else None,
        simulation_only=True,
        scheduler=status,
        account=account(db, run),
        drawdown=drawdown(curve),
        attribution=analysis,
        positions=positions,
        signals=recent,
        wallets=sorted(ranked, key=lambda r: r["score"] or -1, reverse=True),
        equity=[
            dict(
                at=r.captured_at,
                equity=r.equity,
                realized=r.realized_pnl,
                unrealized=r.unrealized_pnl,
                quality=r.quality,
            )
            for r in curve[-1000:]
        ],
        quality=dict(
            Counter(
                r.category
                for r in db.query(V3Quality).filter(
                    V3Quality.created_at >= run.cutover_at
                )
            )
        ),
        funding_basis="public funding rate x last observed held notional; estimated, not exact settlement",
        baseline_frozen=True,
    )
