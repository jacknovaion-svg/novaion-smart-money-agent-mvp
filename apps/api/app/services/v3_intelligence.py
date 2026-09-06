"""Versioned, as-of intelligence. Never overwrites wallet scores or signal events."""

import json
import math
import statistics
from collections import defaultdict
from datetime import timedelta, timezone
from sqlalchemy.orm import load_only

from app.models.market_data import WalletFill, WalletPositionSnapshot
from app.models.signal import Signal
from app.models.system_log import SystemLog
from app.models.v3 import V3WalletEvaluation, V3Lifecycle, V3Trade, V3Quality
from app.services.v3_shadow import utc, now_utc, encode


def clamp(value):
    return min(1.0, max(0.0, value))


def pnl_metrics(values):
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    return dict(
        samples=len(values),
        net_pnl=sum(values),
        win_rate=len(wins) / len(values) if values else None,
        profit_factor=sum(wins) / -sum(losses) if losses else None,
        expectancy=statistics.mean(values) if values else None,
        average_winner=statistics.mean(wins) if wins else None,
        average_loser=statistics.mean(losses) if losses else None,
        median_pnl=statistics.median(values) if values else None,
    )


def source_positions(snapshot):
    try:
        return (
            {p["coin"]: p for p in json.loads(snapshot.positions_json)}
            if snapshot
            else {}
        )
    except (ValueError, TypeError, KeyError):
        return {}


def signal_context(db, signal, cfg):
    # The snapshot encoded by the immutable event is preferable to today's position.
    parts = (signal.dedupe_key or "").split(":")
    after = None
    if len(parts) >= 2 and parts[0] == str(signal.wallet_id) and parts[1].isdigit():
        candidate = db.get(WalletPositionSnapshot, int(parts[1]))
        if (
            candidate
            and candidate.wallet_id == signal.wallet_id
            and utc(candidate.created_at) <= utc(signal.created_at)
        ):
            after = candidate
    if after is None:
        after = (
            db.query(WalletPositionSnapshot)
            .filter(
                WalletPositionSnapshot.wallet_id == signal.wallet_id,
                WalletPositionSnapshot.created_at <= signal.created_at,
            )
            .order_by(
                WalletPositionSnapshot.created_at.desc(),
                WalletPositionSnapshot.id.desc(),
            )
            .first()
        )
    before = None
    if after:
        before = (
            db.query(WalletPositionSnapshot)
            .filter(
                WalletPositionSnapshot.wallet_id == signal.wallet_id,
                WalletPositionSnapshot.id < after.id,
                WalletPositionSnapshot.created_at <= after.created_at,
            )
            .order_by(WalletPositionSnapshot.id.desc())
            .first()
        )
    old = source_positions(before).get(signal.symbol, {})
    new = source_positions(after).get(signal.symbol, {})
    oq = float(old.get("signed_size", 0))
    nq = float(new.get("signed_size", 0))
    side = (
        "long"
        if nq > 0
        else (
            "short"
            if nq < 0
            else "long" if oq > 0 else "short" if oq < 0 else signal.side
        )
    )
    action = signal.signal_type.upper()
    if oq * nq < 0:
        action = "FLIP"
    valid = bool(before and after)
    if valid:
        if action == "OPEN":
            valid = oq == 0 and nq != 0
        elif action == "ADD":
            valid = oq * nq > 0 and abs(nq) > abs(oq)
        elif action == "REDUCE":
            valid = oq * nq > 0 and 0 < abs(nq) < abs(oq)
        elif action == "CLOSE":
            valid = oq != 0 and nq == 0
        elif action == "FLIP":
            valid = oq * nq < 0
        else:
            valid = False
    delta = abs(abs(nq) - abs(oq)) if action != "FLIP" else abs(nq) + abs(oq)
    change_usd = delta * float(signal.current_price or 0)
    change_pct = delta / abs(oq) if oq else 1.0
    stale = (
        not after
        or (utc(signal.created_at) - utc(after.created_at)).total_seconds()
        > cfg["v3_sync_max_age_seconds"]
    )
    gap = (
        not before
        or not after
        or (utc(after.created_at) - utc(before.created_at)).total_seconds()
        > cfg["v3_sync_max_age_seconds"]
    )
    return dict(
        action=action,
        side=side,
        before_quantity=oq,
        after_quantity=nq,
        change_usd=change_usd,
        change_pct=change_pct,
        snapshot_id=after.id if after else None,
        position_change_valid=valid,
        stale_snapshot=stale,
        snapshot_gap=gap,
    )


def evaluate_wallet(db, wallet_id, as_of, cfg, persist=True):
    as_of = utc(as_of)
    if persist:
        cached = (
            db.query(V3WalletEvaluation)
            .filter(
                V3WalletEvaluation.wallet_id == wallet_id,
                V3WalletEvaluation.as_of <= as_of,
                V3WalletEvaluation.as_of
                >= as_of - timedelta(seconds=cfg["v3_evaluation_cache_seconds"]),
                V3WalletEvaluation.model_version == "v3.0",
            )
            .order_by(V3WalletEvaluation.as_of.desc())
            .first()
        )
        if cached:
            return cached
    start = as_of - timedelta(days=30)
    fills = (
        db.query(WalletFill)
        .filter(
            WalletFill.wallet_id == wallet_id,
            WalletFill.trade_time >= start,
            WalletFill.trade_time <= as_of,
            WalletFill.created_at <= as_of,
        )
        .order_by(WalletFill.trade_time, WalletFill.id)
        .all()
    )
    snaps = (
        db.query(WalletPositionSnapshot)
        .options(
            load_only(
                WalletPositionSnapshot.created_at,
                WalletPositionSnapshot.account_value,
                WalletPositionSnapshot.positions_json,
            )
        )
        .filter(
            WalletPositionSnapshot.wallet_id == wallet_id,
            WalletPositionSnapshot.created_at >= start,
            WalletPositionSnapshot.created_at <= as_of,
        )
        .order_by(WalletPositionSnapshot.created_at)
        .all()
    )
    # Fill-level closes are explicitly not labeled completed round trips.
    closes = []
    daily = defaultdict(float)
    symbols = defaultdict(float)
    durations = []
    opened = {}
    signed = []
    for f in fills:
        raw = json.loads(f.raw_json or "{}")
        direction = str(raw.get("dir", ""))
        net = float(f.closed_pnl or 0) - abs(float(f.fee or 0))
        daily[utc(f.trade_time).date().isoformat()] += net
        if f.closed_pnl or "Close" in direction or ">" in direction:
            closes.append(net)
            symbols[f.coin] += net
        try:
            prior = float(raw["startPosition"])
            delta = float(f.size) * (1 if f.side == "B" else -1)
            remaining = prior + delta
        except (KeyError, TypeError, ValueError):
            continue
        signed.append(delta)
        if prior == 0 and remaining != 0:
            opened[f.coin] = utc(f.trade_time)
        if (remaining == 0 or prior * remaining < 0) and f.coin in opened:
            durations.append((utc(f.trade_time) - opened.pop(f.coin)).total_seconds())
        if prior * remaining < 0:
            opened[f.coin] = utc(f.trade_time)
    values = [float(f.closed_pnl or 0) - abs(float(f.fee or 0)) for f in fills]
    m = pnl_metrics(closes)
    net = sum(values)
    gross = sum(float(f.closed_pnl or 0) for f in fills)
    wins = [v for v in closes if v > 0]
    active = len(daily)
    concentration = max(wins) / sum(wins) if wins else None
    equity = snaps[-1].account_value if snaps else None
    equities = [s.account_value for s in snaps if s.account_value > 0]
    positions = [p for s in snaps for p in source_positions(s).values()]
    avg_position = (
        statistics.mean(abs(float(p.get("position_value", 0))) for p in positions)
        if positions
        else None
    )
    max_lev = max((float(p.get("leverage", 1)) for p in positions), default=None)
    consistency = sum(v > 0 for v in daily.values()) / active if active else 0
    frequency = len(fills) / max(active, 1)
    holding = statistics.median(durations) if durations else None
    copyability = 100 * (
        0.5 * clamp(1 - frequency / 288)
        + 0.3 * clamp((holding or 0) / 900)
        + 0.2 * clamp(1 - (max_lev or 20) / 30)
    )
    # Without observed holding periods, profitability does not imply copyability.
    copy_label = (
        "GOOD TO COPY"
        if copyability >= 70 and len(durations) >= cfg["v3_min_samples"]
        else "OBSERVE ONLY" if copyability >= 40 else "NOT COPYABLE"
    )
    eligible = (
        len(closes) >= cfg["v3_min_samples"]
        and active >= cfg["v3_min_active_days"]
        and equity is not None
        and equity >= cfg["v3_min_account_equity"]
    )
    components = {
        "pnl": clamp(0.5 + net / (2 * max(equity or 1, 1))),
        "pf": clamp((m["profit_factor"] or 0) / 2),
        "expectancy": clamp(
            0.5
            + (m["expectancy"] or 0)
            / max(statistics.mean(abs(x) for x in closes) if closes else 1, 1)
            / 2
        ),
        "consistency": consistency,
        "concentration": 1 - (concentration if concentration is not None else 1),
        "activity": clamp(active / 30),
        "risk": clamp(1 - (max_lev or 20) / 30),
    }
    weights = {k: cfg["v3_score_" + k + "_weight"] for k in components}
    score = (
        100
        * sum(components[k] * weights[k] for k in components)
        / max(sum(weights.values()), 1)
    )
    if not eligible:
        score = min(score, cfg["v3_tier_b"] - 1)
    # Unknown funding/flows prevent an S rating and exact ROI or source-equity drawdown.
    score = min(score, cfg["v3_tier_s"] - 1)
    tier = next(
        (
            label
            for label, key in [
                ("S", "v3_tier_s"),
                ("A", "v3_tier_a"),
                ("B", "v3_tier_b"),
                ("C", "v3_tier_c"),
            ]
            if score >= cfg[key]
        ),
        "Reject",
    )
    recent = sum(
        v
        for day, v in daily.items()
        if day >= (as_of - timedelta(days=7)).date().isoformat()
    )
    m.update(
        gross_pnl=gross,
        net_after_fees=net,
        fees=sum(abs(float(f.fee or 0)) for f in fills),
        funding_included=False,
        roi=None,
        max_drawdown=None,
        unavailable_reasons=[
            "external_cashflows_unavailable",
            "funding_coverage_unknown",
            "fill_closes_not_round_trips",
        ],
        trade_count=len(fills),
        close_fill_count=len(closes),
        active_days=active,
        consistency=consistency,
        profit_concentration=concentration,
        average_position_size=avg_position,
        account_equity=equity,
        capital_stability_cv=(
            statistics.pstdev(equities) / statistics.mean(equities)
            if len(equities) > 1
            else None
        ),
        loss_tail=min(closes) if closes else None,
        holding_time_median=holding,
        holding_samples=len(durations),
        holding_time_average=statistics.mean(durations) if durations else None,
        symbols=len(symbols),
        directional_bias=sum(x > 0 for x in signed) / len(signed) if signed else None,
        recent_net_pnl=recent,
        prior_daily_net_pnl=(net - recent) / 23,
        recent_daily_net_pnl=recent / 7,
        sharpe_like_daily_pnl=(
            statistics.mean(daily.values()) / statistics.pstdev(daily.values())
            if active > 1 and statistics.pstdev(daily.values())
            else None
        ),
        fill_frequency_per_active_day=frequency,
        minimum_sample_pass=eligible,
        estimated=True,
        window_start=start,
        window_end=as_of,
        first_observed_fill=fills[0].trade_time if fills else None,
        components=components,
        weights=weights,
    )
    row = V3WalletEvaluation(
        wallet_id=wallet_id,
        score=round(score, 2),
        tier=tier,
        copyability=round(copyability, 2),
        copy_label=copy_label,
        quality="ESTIMATED" if eligible else "INSUFFICIENT",
        metrics_json=encode(m),
        as_of=as_of,
    )
    if persist:
        db.add(row)
        db.commit()
    return row


def evaluate_signal(db, signal, cfg, regime=None):
    context = signal_context(db, signal, cfg)
    wallet = evaluate_wallet(db, signal.wallet_id, signal.created_at, cfg)
    since = utc(signal.created_at) - timedelta(minutes=15)
    failures = (
        db.query(SystemLog)
        .filter(
            SystemLog.created_at >= since,
            SystemLog.created_at <= signal.created_at,
            SystemLog.level.in_(["ERROR", "CRITICAL"]),
        )
        .count()
    )
    noise = (
        db.query(Signal)
        .filter(
            Signal.wallet_id == signal.wallet_id,
            Signal.symbol == signal.symbol,
            Signal.created_at >= since,
            Signal.created_at < signal.created_at,
        )
        .count()
    )
    quality = not (context["stale_snapshot"] or context["snapshot_gap"] or failures)
    score = (
        0.45 * wallet.score
        + 0.25 * wallet.copyability
        + 0.2 * max(0, 100 - float(signal.risk_score or 0))
        + 0.1 * max(0, 100 - noise * 10)
    )
    reason = ""
    if not context["position_change_valid"]:
        reason = "missing_or_invalid_position_snapshot"
    elif not quality:
        reason = "data_quality_gate"
    elif not json.loads(wallet.metrics_json)["minimum_sample_pass"]:
        reason = "insufficient_wallet_samples"
    elif float(signal.risk_score or 0) > 80:
        reason = "high_risk"
    elif context["action"] in {"ADD", "REDUCE"} and (
        context["change_usd"] < cfg["v3_min_change_usd"]
        or context["change_pct"] < cfg["v3_min_change_pct"]
    ):
        reason = "small_position_change"
    elif wallet.copyability < cfg["v3_min_copyability"]:
        reason = "copyability_gate"
    elif score < cfg["v3_min_signal_score"]:
        reason = "signal_quality_gate"
    lifecycle = (
        db.query(V3Lifecycle)
        .filter_by(wallet_id=signal.wallet_id)
        .order_by(V3Lifecycle.id.desc())
        .first()
    )
    if lifecycle and lifecycle.state in {"Demoted", "Rejected", "Probation"}:
        reason = "wallet_lifecycle_gate"
    return dict(
        **context,
        eligible=not reason,
        reason=reason,
        exit_valid=context["position_change_valid"],
        signal_score=round(score, 2),
        wallet_score=wallet.score,
        tier=wallet.tier,
        copyability=wallet.copyability,
        data_quality="GOOD" if quality else "DEGRADED",
        regime=regime or dict(trend="UNKNOWN", volatility="UNKNOWN"),
        evaluation_id=wallet.id,
        as_of=signal.created_at,
        model_version="v3.0"
    )


def market_regime(candles, as_of, cfg):
    prices = [
        float(c["c"])
        for c in sorted(candles, key=lambda c: c["T"])
        if int(c["T"])
        <= int(utc(as_of).replace(tzinfo=timezone.utc).timestamp() * 1000)
    ]
    if len(prices) < 25 or any(p <= 0 or not math.isfinite(p) for p in prices):
        return dict(trend="UNKNOWN", volatility="UNKNOWN")
    change = prices[-1] / prices[-25] - 1
    returns = [math.log(b / a) for a, b in zip(prices[-25:-1], prices[-24:])]
    vol = statistics.pstdev(returns) * math.sqrt(24)
    return dict(
        trend=(
            "BULL"
            if change > cfg["v3_trend_threshold"]
            else "BEAR" if change < -cfg["v3_trend_threshold"] else "SIDEWAYS"
        ),
        volatility="HIGH" if vol > cfg["v3_volatility_threshold"] else "LOW",
        daily_change=change,
        daily_volatility=vol,
    )


def update_lifecycle(db, run, cfg, at=None):
    at = at or now_utc()
    for (wid,) in db.query(V3WalletEvaluation.wallet_id).distinct():
        evaluation = (
            db.query(V3WalletEvaluation)
            .filter_by(wallet_id=wid)
            .order_by(V3WalletEvaluation.as_of.desc())
            .first()
        )
        previous = (
            db.query(V3Lifecycle)
            .filter_by(wallet_id=wid)
            .order_by(V3Lifecycle.id.desc())
            .first()
        )
        if (
            previous
            and (at - utc(previous.created_at)).total_seconds()
            < cfg["v3_lifecycle_hours"] * 3600
        ):
            continue
        trades = (
            db.query(V3Trade)
            .filter_by(run_id=run.id, wallet_id=wid, status="closed")
            .all()
        )
        m = pnl_metrics([t.net_pnl for t in trades])
        state = "Watchlist"
        reason = "forward_samples_insufficient"
        if len(trades) >= cfg["v3_min_forward_closed"]:
            if (
                m["net_pnl"] > 0
                and (m["profit_factor"] or 0) > 1
                and evaluation.tier in {"S", "A"}
            ):
                state = (
                    "Elite"
                    if len(trades) >= 2 * cfg["v3_min_forward_closed"]
                    and (m["profit_factor"] or 0) > 1.5
                    else "Approved"
                )
                reason = "positive_forward_net_samples"
            elif m["net_pnl"] < 0:
                state = (
                    "Demoted"
                    if previous and previous.state == "Probation"
                    else "Probation"
                )
                reason = "negative_forward_net_samples"
        if evaluation.tier == "Reject":
            state = "Rejected"
            reason = "low_quality_score"
        if not previous or state != previous.state:
            db.add(
                V3Lifecycle(
                    wallet_id=wid,
                    state=state,
                    previous=previous.state if previous else "Candidate",
                    reason=reason,
                    evaluation_id=evaluation.id,
                    created_at=at,
                )
            )
    db.commit()
