"""Forward-only simulation ledger. No signal mutation or exchange order client."""

import json
import math
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text, or_, and_

from app.core.config import get_settings
from app.models.signal import Signal
from app.models.system_log import SystemLog
from app.models.v3 import (
    V3Run,
    V3Processing,
    V3Position,
    V3Trade,
    V3Action,
    V3Equity,
    V3Quality,
)


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    )


def encode(value):
    return json.dumps(value, default=str, allow_nan=False, sort_keys=True)


@contextmanager
def atomic(db):
    # Acquire SQLite's writer reservation before reading funds or consumption state.
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("V3 transaction requires a clean session")
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def config_values():
    s = get_settings()
    values = {
        key: getattr(s, key) for key in type(s).model_fields if key.startswith("v3_")
    }
    values.update(fee_rate=s.paper_taker_fee_rate, slippage_rate=s.paper_slippage_rate)
    for key in (
        "v3_starting_balance",
        "v3_margin_usd",
        "v3_max_position_usd",
        "v3_max_leverage",
        "v3_min_notional",
    ):
        if not math.isfinite(values[key]) or values[key] <= 0:
            raise ValueError(f"Invalid {key}")
    if not 0 < values["v3_fill_fraction"] <= 1:
        raise ValueError("Invalid fill fraction")
    if not 0 <= values["fee_rate"] < 0.05 or not 0 <= values["slippage_rate"] < 0.1:
        raise ValueError("Invalid cost configuration")
    return values


def safety():
    s = get_settings()
    if (
        not s.v3_enabled
        or not s.validation_mode
        or s.enable_live_trading
        or not s.emergency_stop
    ):
        raise ValueError(
            "V3 requires enabled simulation with live trading disabled and emergency stop on"
        )


def ensure_run(db):
    safety()
    s = get_settings()
    if not s.shadow_v3_cutover_at:
        raise ValueError(
            "SHADOW_V3_CUTOVER_AT is required; legacy Paper cutover is never used"
        )
    cutover = utc(s.shadow_v3_cutover_at)
    with atomic(db):
        run = db.query(V3Run).filter_by(version=s.shadow_v3_version).first()
        if run:
            if (
                run.cutover_at != cutover
                or json.loads(run.config_json) != config_values()
            ):
                raise ValueError("Frozen V3 cutover/config mismatch")
        else:
            if abs((now_utc() - cutover).total_seconds()) > 600:
                raise ValueError("New V3 cutover must be the current activation time")
            high = db.query(func.max(Signal.id)).scalar() or 0
            run = V3Run(
                version=s.shadow_v3_version,
                cutover_at=cutover,
                high_water_id=high,
                config_json=encode(config_values()),
            )
            db.add(run)
            db.flush()
            db.add(
                SystemLog(
                    level="INFO",
                    module="v3_shadow",
                    message="V3 forward-only cutover established",
                    payload_json=encode(
                        dict(
                            version=run.version, cutover_at=cutover, high_water_id=high
                        )
                    ),
                )
            )
    return run


def account(db, run, at=None):
    cfg = json.loads(run.config_json)
    actions = db.query(V3Action).filter_by(run_id=run.id).all()
    positions = (
        db.query(V3Position)
        .filter(V3Position.run_id == run.id, V3Position.state != "FLAT")
        .all()
    )
    realized = sum(a.net_pnl for a in actions)
    unrealized = sum(p.unrealized_pnl for p in positions)
    used = sum(p.margin for p in positions)
    equity = cfg["v3_starting_balance"] + realized + unrealized
    time = at or now_utc()
    stale = any(
        p.marked_at is None
        or (time - utc(p.marked_at)).total_seconds() > cfg["v3_sync_max_age_seconds"]
        or p.quality != "GOOD"
        for p in positions
    )
    return dict(
        starting_balance=cfg["v3_starting_balance"],
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        total_pnl=realized + unrealized,
        balance=cfg["v3_starting_balance"] + realized,
        equity=equity,
        used_margin=used,
        available_funds_raw=equity - used,
        quality="DEGRADED" if stale else "GOOD",
    )


def snapshot(db, run, at):
    db.flush()
    metrics = account(db, run, at)
    row = V3Equity(
        run_id=run.id,
        captured_at=at,
        **{
            k: metrics[k]
            for k in (
                "realized_pnl",
                "unrealized_pnl",
                "total_pnl",
                "equity",
                "used_margin",
                "quality",
            )
        },
    )
    db.add(row)
    return row


def position_state(position):
    return {
        key: getattr(position, key)
        for key in (
            "state",
            "trade_id",
            "quantity",
            "average_entry",
            "reference_entry",
            "margin",
            "leverage",
            "mark_price",
        )
    }


def add_action(
    db,
    run,
    processing,
    position,
    trade,
    kind,
    qty,
    price,
    reference,
    gross=0.0,
    fees=0.0,
    slip=0.0,
    funding=0.0,
    key=None,
    at=None,
):
    net = gross - fees - slip - funding
    for name, amount in (
        ("gross_pnl", gross),
        ("fees", fees),
        ("slippage", slip),
        ("funding", funding),
        ("net_pnl", net),
    ):
        setattr(trade, name, (getattr(trade, name) or 0) + amount)
    db.add(
        V3Action(
            run_id=run.id,
            processing_id=processing.id if processing else None,
            trade_id=trade.id,
            event_key=key or f"{run.version}:{processing.signal_id}:{kind}",
            action=kind,
            quantity=qty,
            price=price,
            reference_price=reference,
            gross_pnl=gross,
            fees=fees,
            slippage=slip,
            funding=funding,
            net_pnl=net,
            position_after_json=encode(position_state(position)),
            created_at=at or now_utc(),
        )
    )


def quote_price(quote, buying, cfg):
    raw = quote["ask"] if buying else quote["bid"]
    return raw * (1 + cfg["slippage_rate"] if buying else 1 - cfg["slippage_rate"])


def mark(position, quote, cfg, at):
    position.mark_price = quote["mid"]
    position.marked_at = utc(quote["observed_at"])
    position.updated_at = at
    if position.state == "FLAT":
        position.unrealized_pnl = 0
        return
    direction = 1 if position.state == "OPEN_LONG" else -1
    exit_price = quote_price(quote, direction < 0, cfg)
    gross = direction * position.quantity * (quote["mid"] - position.reference_entry)
    exit_cost = direction * position.quantity * (quote["mid"] - exit_price)
    position.mark_price = quote["mid"]
    position.unrealized_pnl = (
        gross - exit_cost - position.quantity * exit_price * cfg["fee_rate"]
    )
    position.marked_at = utc(quote["observed_at"])
    position.updated_at = at
    position.quality = "GOOD"


def valid_quote(quote, cfg, at):
    if not quote:
        return False
    try:
        if any(
            not math.isfinite(float(quote.get(k, 0))) or float(quote.get(k, 0)) <= 0
            for k in ("mid", "bid", "ask")
        ):
            return False
        age = (at - utc(quote["observed_at"])).total_seconds()
        return (
            0 <= age <= cfg["v3_quote_max_age_seconds"]
            and quote["bid"] <= quote["mid"] <= quote["ask"]
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def enter(db, run, event, p, signal, side, quote, cfg, margin, at, adding=False):
    if (quote["ask"] - quote["bid"]) / quote["mid"] > cfg["v3_max_spread_pct"]:
        return "spread_too_wide"
    price = quote_price(quote, side == "long", cfg)
    leverage = (
        p.leverage
        if adding
        else min(max(float(signal.source_leverage or 1), 1), cfg["v3_max_leverage"])
    )
    qty = margin * leverage / price * cfg["v3_fill_fraction"]
    depth = quote.get("ask_quantity" if side == "long" else "bid_quantity")
    if depth is not None:
        qty = min(qty, max(0, float(depth)))
    actual_margin = qty * price / leverage
    if qty * price < cfg["v3_min_notional"]:
        return "minimum_notional"
    if p.margin + actual_margin > cfg["v3_max_position_usd"] + 1e-9:
        return "max_position"
    direction = 1 if side == "long" else -1
    fees = qty * price * cfg["fee_rate"]
    slip = direction * qty * (price - quote["mid"])
    funds = account(db, run, at)
    if funds["quality"] != "GOOD":
        return "stale_account_marks"
    exit_price = quote_price(quote, side == "short", cfg)
    reserve = (
        max(0, direction * qty * (quote["mid"] - exit_price))
        + qty * exit_price * cfg["fee_rate"]
    )
    if actual_margin + fees + slip + reserve > funds["available_funds_raw"] + 1e-9:
        return "insufficient_shadow_funds"
    if not adding:
        trade = V3Trade(
            run_id=run.id,
            position_id=p.id,
            signal_id=signal.id,
            wallet_id=signal.wallet_id,
            symbol=signal.symbol,
            side=side,
            opened_at=at,
            context_json=event.evaluation_json,
        )
        db.add(trade)
        db.flush()
        p.trade_id = trade.id
    else:
        trade = db.get(V3Trade, p.trade_id)
    total = p.quantity + qty
    p.average_entry = (p.average_entry * p.quantity + price * qty) / total
    p.reference_entry = (p.reference_entry * p.quantity + quote["mid"] * qty) / total
    p.quantity = total
    p.margin += actual_margin
    p.leverage = leverage
    p.state = "OPEN_LONG" if side == "long" else "OPEN_SHORT"
    mark(p, quote, cfg, at)
    add_action(
        db,
        run,
        event,
        p,
        trade,
        "ADD" if adding else "OPEN",
        qty,
        price,
        quote["mid"],
        fees=fees,
        slip=slip,
        at=at,
    )
    return ""


def exit_position(db, run, event, p, quote, cfg, fraction, at):
    direction = 1 if p.state == "OPEN_LONG" else -1
    qty = p.quantity * fraction
    price = quote_price(quote, direction < 0, cfg)
    gross = direction * qty * (quote["mid"] - p.reference_entry)
    slip = direction * qty * (quote["mid"] - price)
    fee = qty * price * cfg["fee_rate"]
    trade = db.get(V3Trade, p.trade_id)
    p.quantity -= qty
    p.margin *= 1 - fraction
    kind = "CLOSE" if fraction == 1 else "REDUCE"
    if fraction == 1:
        p.state = "FLAT"
        p.quantity = 0
        p.margin = 0
        p.unrealized_pnl = 0
        trade.status = "closed"
        trade.closed_at = at
        p.average_entry = 0
        p.reference_entry = 0
    mark(p, quote, cfg, at)
    add_action(
        db,
        run,
        event,
        p,
        trade,
        kind,
        qty,
        price,
        quote["mid"],
        gross,
        fee,
        slip,
        at=at,
    )


def process_one(db, run_id, signal_id, evaluation, quote, at=None):
    safety()
    at = utc(at) if at else now_utc()
    with atomic(db):
        run = db.get(V3Run, run_id)
        signal = db.get(Signal, signal_id)
        if signal.id <= run.high_water_id or utc(signal.created_at) <= run.cutover_at:
            return "historical"
        event = (
            db.query(V3Processing)
            .filter_by(signal_id=signal.id, shadow_version=run.version)
            .first()
        )
        if event and event.processing_status in {"processed", "ignored"}:
            return "duplicate"
        cfg = json.loads(run.config_json)
        if (at - utc(signal.created_at)).total_seconds() < cfg[
            "v3_execution_delay_seconds"
        ]:
            return "pending"
        if not event:
            evaluation = dict(
                evaluation,
                execution_latency_seconds=(at - utc(signal.created_at)).total_seconds(),
                quote=quote,
                fill_fraction=cfg["v3_fill_fraction"],
                fee_rate=cfg["fee_rate"],
                slippage_rate=cfg["slippage_rate"],
            )
            event = V3Processing(
                run_id=run.id,
                signal_id=signal.id,
                shadow_version=run.version,
                action=evaluation.get("action", signal.signal_type).upper(),
                evaluation_json=encode(evaluation),
            )
            db.add(event)
            db.flush()
        else:
            evaluation = json.loads(event.evaluation_json)
            event.retry_count += 1
        later = (
            db.query(V3Processing.id)
            .join(Signal, Signal.id == V3Processing.signal_id)
            .filter(
                V3Processing.run_id == run_id,
                V3Processing.processing_status == "processed",
                Signal.wallet_id == signal.wallet_id,
                Signal.symbol == signal.symbol,
                or_(
                    Signal.created_at > signal.created_at,
                    and_(Signal.created_at == signal.created_at, Signal.id > signal.id),
                ),
            )
            .first()
        )
        if later:
            event.processing_status = "ignored"
            event.error = "out_of_order_signal"
            event.processed_at = at
            db.add(
                V3Quality(
                    wallet_id=signal.wallet_id,
                    symbol=signal.symbol,
                    category="out_of_order_signal",
                )
            )
            return "ignored"
        error = ""
        if not valid_quote(quote, cfg, at):
            event.processing_status = "retry"
            event.error = "missing_or_stale_market_price"
            db.add(
                V3Quality(
                    wallet_id=signal.wallet_id,
                    symbol=signal.symbol,
                    category="missing_mark_price",
                )
            )
            return "retry"
        evaluation = dict(
            evaluation,
            execution_quote=quote,
            processed_latency_seconds=(at - utc(signal.created_at)).total_seconds(),
        )
        event.evaluation_json = encode(evaluation)
        p = (
            db.query(V3Position)
            .filter_by(run_id=run.id, wallet_id=signal.wallet_id, symbol=signal.symbol)
            .first()
        )
        if p is None:
            p = V3Position(
                run_id=run.id, wallet_id=signal.wallet_id, symbol=signal.symbol
            )
            db.add(p)
            db.flush()
        kind = event.action
        side = evaluation.get("side", signal.side)
        current = (
            "long"
            if p.state == "OPEN_LONG"
            else "short" if p.state == "OPEN_SHORT" else None
        )
        if current:
            mark(p, quote, cfg, at)
        if kind in {"OPEN", "ADD", "FLIP"}:
            if (at - utc(signal.created_at)).total_seconds() > cfg[
                "v3_signal_max_age_seconds"
            ]:
                error = "stale_signal"
            elif not evaluation.get("eligible", False):
                error = evaluation.get("reason", "quality_gate")
            elif side not in {"long", "short"}:
                error = "missing_side"
            elif (
                not math.isfinite(float(signal.suggested_size_usd or 0))
                or signal.suggested_size_usd <= 0
            ):
                error = "zero_size"
        elif kind in {"REDUCE", "CLOSE"} and not evaluation.get("exit_valid", True):
            error = evaluation.get("reason", "invalid_position_change")
        if not error:
            margin = min(float(signal.suggested_size_usd or 0), cfg["v3_margin_usd"])
            if kind == "OPEN":
                error = (
                    "duplicate_open"
                    if current
                    else enter(db, run, event, p, signal, side, quote, cfg, margin, at)
                )
            elif kind == "ADD":
                error = (
                    "orphan_add"
                    if not current
                    else (
                        "side_mismatch"
                        if current != side
                        else enter(
                            db,
                            run,
                            event,
                            p,
                            signal,
                            side,
                            quote,
                            cfg,
                            margin,
                            at,
                            True,
                        )
                    )
                )
            elif kind in {"REDUCE", "CLOSE"}:
                if not current:
                    error = "orphan_" + kind.lower()
                elif side in {"long", "short"} and current != side:
                    error = "side_mismatch"
                else:
                    exit_position(
                        db,
                        run,
                        event,
                        p,
                        quote,
                        cfg,
                        0.5 if kind == "REDUCE" else 1,
                        at,
                    )
            elif kind == "FLIP":
                if current == side:
                    error = "invalid_flip"
                elif not current:
                    error = "orphan_flip"
                else:
                    # Both legs belong to one transaction; an entry rejection rolls back the flip.
                    with db.begin_nested() as savepoint:
                        exit_position(db, run, event, p, quote, cfg, 1, at)
                        db.flush()
                        error = enter(
                            db, run, event, p, signal, side, quote, cfg, margin, at
                        )
                        if error:
                            savepoint.rollback()
            else:
                error = "unsupported_action"
        event.processing_status = "ignored" if error else "processed"
        event.error = error
        event.processed_at = at
        event.shadow_trade_id = p.trade_id
        if not error and run.started_at is None:
            run.started_at = at
        snapshot(db, run, at)
        return event.processing_status


def pending_ids(db, run, limit=100):
    terminal = db.query(V3Processing.signal_id).filter(
        V3Processing.shadow_version == run.version,
        V3Processing.processing_status.in_(["processed", "ignored"]),
    )
    return [
        r[0]
        for r in db.query(Signal.id)
        .filter(
            Signal.id > run.high_water_id,
            Signal.created_at > run.cutover_at,
            ~Signal.id.in_(terminal),
        )
        .order_by(Signal.id)
        .limit(limit)
    ]


def mark_all(db, run_id, quotes, at=None):
    at = utc(at) if at else now_utc()
    with atomic(db):
        run = db.get(V3Run, run_id)
        cfg = json.loads(run.config_json)
        for p in db.query(V3Position).filter(
            V3Position.run_id == run.id, V3Position.state != "FLAT"
        ):
            quote = quotes.get(p.symbol)
            if valid_quote(quote, cfg, at):
                mark(p, quote, cfg, at)
            else:
                p.quality = "DEGRADED"
                db.add(
                    V3Quality(
                        wallet_id=p.wallet_id,
                        symbol=p.symbol,
                        category="missing_mark_price",
                    )
                )
        snapshot(db, run, at)


def reconcile(db, run_id):
    """Rebuild realized balances and terminal position state solely from the action ledger."""
    actions = db.query(V3Action).filter_by(run_id=run_id).order_by(V3Action.id).all()
    totals = {}
    states = {}
    for a in actions:
        if a.trade_id not in totals:
            totals[a.trade_id] = {
                k: 0.0 for k in ("gross_pnl", "fees", "slippage", "funding", "net_pnl")
            }
        for key in totals[a.trade_id]:
            totals[a.trade_id][key] += getattr(a, key)
        if a.action != "FUNDING":
            trade = db.get(V3Trade, a.trade_id)
            states[trade.position_id] = json.loads(a.position_after_json)
    errors = []
    for trade in db.query(V3Trade).filter_by(run_id=run_id):
        for key, value in totals.get(trade.id, {}).items():
            if not math.isclose(value, getattr(trade, key), rel_tol=1e-9, abs_tol=1e-8):
                errors.append(f"trade:{trade.id}:{key}")
    for pid, state in states.items():
        p = db.get(V3Position, pid)
        for key in (
            "state",
            "trade_id",
            "quantity",
            "margin",
            "average_entry",
            "reference_entry",
            "leverage",
        ):
            actual = getattr(p, key)
            expected = state[key]
            if isinstance(expected, (int, float)):
                if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8):
                    errors.append(f"position:{pid}:{key}")
            elif actual != expected:
                errors.append(f"position:{pid}:{key}")
    return {
        "ok": not errors,
        "errors": errors,
        "ledger_net_pnl": sum(a.net_pnl for a in actions),
    }


def apply_funding(db, run_id, symbol, rates, at=None):
    """Hourly public funding rate applied to auditable held quantity; notional uses last observed price."""
    at = at or now_utc()
    with atomic(db):
        run = db.get(V3Run, run_id)
        for trade in db.query(V3Trade).filter_by(run_id=run_id, symbol=symbol):
            for rate in rates:
                time = datetime.fromtimestamp(
                    int(rate["time"]) / 1000, timezone.utc
                ).replace(tzinfo=None)
                if (
                    time <= trade.opened_at
                    or time > at
                    or (trade.closed_at and time > trade.closed_at)
                ):
                    continue
                key = f"{run.version}:funding:{trade.id}:{rate['time']}"
                if db.query(V3Action.id).filter_by(event_key=key).first():
                    continue
                previous = (
                    db.query(V3Action)
                    .filter(
                        V3Action.trade_id == trade.id,
                        V3Action.created_at < time,
                        V3Action.action != "FUNDING",
                    )
                    .order_by(V3Action.created_at.desc(), V3Action.id.desc())
                    .first()
                )
                if not previous:
                    continue
                state = json.loads(previous.position_after_json)
                cost = (
                    state["quantity"]
                    * state["mark_price"]
                    * float(rate["fundingRate"])
                    * (1 if trade.side == "long" else -1)
                )
                p = db.get(V3Position, trade.position_id)
                add_action(
                    db,
                    run,
                    None,
                    p,
                    trade,
                    "FUNDING",
                    state["quantity"],
                    state["mark_price"],
                    state["mark_price"],
                    funding=cost,
                    key=key,
                    at=time,
                )
            # Settlement price is approximated; this flag remains false until exact coverage exists.
        snapshot(db, run, at)
