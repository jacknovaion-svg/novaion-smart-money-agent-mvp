"""One bounded simulation worker, separate consumption and post-commit notifications."""

import json
import re
import time
import uuid
from datetime import timedelta, timezone
from html.parser import HTMLParser

import httpx
from sqlalchemy import func

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.signal import Signal
from app.models.wallet import Wallet
from app.models.system_log import SystemLog
from app.models.v3 import (
    V3Job,
    V3Run,
    V3Processing,
    V3Position,
    V3Trade,
    V3Action,
    V3Notification,
    V3Quality,
    V3WalletEvaluation,
    V3Lifecycle,
)
from app.services import v3_shadow as ledger
from app.services.v3_intelligence import (
    evaluate_signal,
    evaluate_wallet,
    market_regime,
    update_lifecycle,
)
from app.services.hyperliquid_client import HyperliquidApiClient
from app.services.system_log_service import write_log


def acquire(db, name):
    owner = uuid.uuid4().hex
    now = ledger.now_utc()
    with ledger.atomic(db):
        job = db.get(V3Job, name)
        if job and job.status == "running" and job.expires_at > now:
            return None
        if not job:
            job = V3Job(name=name)
            db.add(job)
        job.owner = owner
        job.status = "running"
        job.expires_at = now + timedelta(minutes=10)
    return owner


def heartbeat(db, name, owner):
    with ledger.atomic(db):
        job = db.get(V3Job, name)
        if job.owner != owner:
            raise RuntimeError("V3 worker lease lost")
        job.expires_at = ledger.now_utc() + timedelta(minutes=10)


def finish(db, name, owner, result, status="ok"):
    with ledger.atomic(db):
        job = db.get(V3Job, name)
        if job.owner == owner:
            job.status = status
            job.finished_at = ledger.now_utc()
            job.result_json = ledger.encode(result)


def quality_event(db, category, details=None, wallet_id=None, symbol=""):
    db.rollback()
    db.add(
        V3Quality(
            category=category,
            details_json=ledger.encode(details or {}),
            wallet_id=wallet_id,
            symbol=symbol,
        )
    )
    db.commit()


def collect_quality(db, run):
    last = db.query(func.max(V3Quality.source_log_id)).scalar() or 0
    logs = (
        db.query(SystemLog)
        .filter(
            SystemLog.id > last,
            SystemLog.created_at > run.cutover_at,
            SystemLog.level.in_(["WARNING", "ERROR", "CRITICAL"]),
        )
        .order_by(SystemLog.id)
        .limit(500)
        .all()
    )
    for row in logs:
        text = (row.message + " " + row.payload_json).lower()
        if row.module == "hyperliquid":
            category = "hyperliquid_429" if "429" in text else "hyperliquid_failure"
        elif "sync" in text:
            category = "wallet_sync_failure"
        elif "performance" in text or "quality" in text:
            category = "performance_update_failure"
        else:
            category = "system_warning"
        payload = json.loads(row.payload_json or "{}")
        db.add(
            V3Quality(
                source_log_id=row.id,
                category=category,
                wallet_id=payload.get("wallet_id"),
                details_json=ledger.encode({"module": row.module, "level": row.level}),
                created_at=row.created_at,
            )
        )
    db.commit()


def market_quote(client, symbol):
    book = client.post_info({"type": "l2Book", "coin": symbol}, weight=2)
    bid = book["levels"][0][0]
    ask = book["levels"][1][0]
    return dict(
        bid=float(bid["px"]),
        ask=float(ask["px"]),
        mid=(float(bid["px"]) + float(ask["px"])) / 2,
        bid_quantity=float(bid["sz"]),
        ask_quantity=float(ask["sz"]),
        observed_at=__import__("datetime")
        .datetime.fromtimestamp(book["time"] / 1000, timezone.utc)
        .replace(tzinfo=None),
    )


def queue_high_value(db, run, event):
    cfg = json.loads(run.config_json)
    evaluation = json.loads(event.evaluation_json)
    if event.processing_status != "processed" or event.action not in {
        "OPEN",
        "CLOSE",
        "FLIP",
    }:
        return
    trade = db.get(V3Trade, event.shadow_trade_id) if event.shadow_trade_id else None
    important_result = (
        event.action == "CLOSE"
        and trade
        and abs(trade.net_pnl) >= cfg["v3_telegram_pnl_usd"]
    )
    if not important_result and (
        evaluation.get("signal_score", 0) < cfg["v3_telegram_min_score"]
        or evaluation.get("tier") not in {"S", "A"}
    ):
        return
    s = db.get(Signal, event.signal_id)
    w = db.get(Wallet, s.wallet_id)
    key = f"{run.version}:signal:{s.id}"
    if db.query(V3Notification.id).filter_by(event_key=key).first():
        return
    action = {"OPEN": "模拟开仓", "CLOSE": "模拟平仓", "FLIP": "模拟方向反转"}[
        event.action
    ]
    body = (
        f"【NOVAION｜V3 高价值事件｜仅模拟】\n钱包：{w.address[:6]}...{w.address[-4:]}\n币种：{s.symbol}\n方向："
        + ("做多" if evaluation.get("side") == "long" else "做空")
    )
    body += f'\n系统动作：{action}\n源钱包仓位变化：${evaluation.get("change_usd",0):.2f}\n钱包评分：{evaluation.get("wallet_score")} / {evaluation.get("tier")}\n信号质量：{evaluation.get("signal_score")}\n可跟随性：{evaluation.get("copyability")}\n账户净权益：${ledger.account(db,run)["equity"]:.2f}\n结论：已记录前向模拟样本，尚不代表收益能力已验证。'
    db.add(V3Notification(event_key=key, body=body))
    db.commit()


def queue_lifecycle(db, run):
    for row in db.query(V3Lifecycle).filter(
        V3Lifecycle.created_at > run.cutover_at,
        V3Lifecycle.state.in_(["Elite", "Probation", "Demoted", "Rejected"]),
    ):
        key = f"{run.version}:lifecycle:{row.id}"
        if db.query(V3Notification.id).filter_by(event_key=key).first():
            continue
        w = db.get(Wallet, row.wallet_id)
        db.add(
            V3Notification(
                event_key=key,
                body=f"【NOVAION｜钱包观察调整｜仅模拟】\n钱包：{w.address[:6]}...{w.address[-4:]}\n状态：{row.previous} → {row.state}\n结论：依据版本化评分与前向样本调整 Shadow 资格，不删除历史，不执行真实交易。",
            )
        )
    db.commit()


def daily_notification(db):
    from app.services.v3_reporting import attribution

    run = db.query(V3Run).order_by(V3Run.id.desc()).first()
    if not run:
        return False
    key = f"{run.version}:daily:{ledger.now_utc().date().isoformat()}"
    if not db.query(V3Notification.id).filter_by(event_key=key).first():
        a = ledger.account(db, run)
        report = attribution(db, run)
        m = report["summary"]
        body = (
            f'【NOVAION｜V3 前向验证日报｜仅模拟】\n初始本金：${a["starting_balance"]:.2f}\n账户净权益：${a["equity"]:.2f}\n已实现净收益：${a["realized_pnl"]:.2f}\n预计净浮动收益：${a["unrealized_pnl"]:.2f}\n占用保证金：${a["used_margin"]:.2f}\nShadow 交易：{m["trades"]}\n已平仓：{m["closed_trades"]}\n结论：'
            + (
                "样本不足，继续前向模拟观察。"
                if report["validation"]["grade"] == "INSUFFICIENT DATA"
                else "查看前向净收益与数据完整性后再评价，模拟结果不代表未来收益。"
            )
        )
        db.add(V3Notification(event_key=key, body=body))
        db.commit()
    return send_pending(db) > 0


def send_pending(db):
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return 0
    sent = 0
    for (row_id,) in (
        db.query(V3Notification.id).filter_by(status="pending").limit(20).all()
    ):
        with ledger.atomic(db):
            row = db.get(V3Notification, row_id)
            if row.status != "pending":
                continue
            row.status = "sending"
            body = row.body
        # A timeout can mean delivered-but-response-lost. Do not automatically resend an unknown outcome.
        try:
            response = httpx.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": settings.telegram_chat_id, "text": body},
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise ValueError("Telegram rejected request")
            with ledger.atomic(db):
                row = db.get(V3Notification, row_id)
                row.status = "sent"
                row.message_id = str(payload["result"]["message_id"])
            sent += 1
        except Exception as exc:
            with ledger.atomic(db):
                row = db.get(V3Notification, row_id)
                row.status = "unknown"
                row.error = type(exc).__name__
            # Never log exception URLs: Telegram URLs contain the token.
    return sent


def cycle(db=None, client=None):
    own = db is None
    db = db or SessionLocal()
    name = "shadow_v3_cycle"
    owner = None
    try:
        if not get_settings().v3_enabled:
            return {"disabled": True}
        run = ledger.ensure_run(db)
        cfg = json.loads(run.config_json)
        run_id = run.id
        owner = acquire(db, name)
        if not owner:
            return {"locked": True}
        client = client or HyperliquidApiClient(db)
        collect_quality(db, run)
        result = {
            "processed": 0,
            "ignored": 0,
            "retry": 0,
            "pending": 0,
            "errors": 0,
            "marks": 0,
        }
        ids = ledger.pending_ids(db, run)
        symbols = {
            r[0]
            for r in db.query(V3Position.symbol).filter(
                V3Position.run_id == run_id, V3Position.state != "FLAT"
            )
        }
        symbols.update(s[0] for s in db.query(Signal.symbol).filter(Signal.id.in_(ids)))
        quotes = {}
        for symbol in sorted(symbols):
            heartbeat(db, name, owner)
            try:
                quotes[symbol] = market_quote(client, symbol)
            except Exception as exc:
                quality_event(
                    db,
                    "missing_mark_price",
                    {"exception": type(exc).__name__},
                    symbol=symbol,
                )
        ledger.mark_all(db, run_id, quotes)
        result["marks"] = len(quotes)
        candles = []
        if ids:
            try:
                end = int(
                    ledger.now_utc().replace(tzinfo=timezone.utc).timestamp() * 1000
                )
                candles = client.post_info(
                    {
                        "type": "candleSnapshot",
                        "req": {
                            "coin": "BTC",
                            "interval": "1h",
                            "startTime": end - 48 * 3600000,
                            "endTime": end,
                        },
                    },
                    weight=20,
                )
            except Exception as exc:
                quality_event(db, "missing_regime", {"exception": type(exc).__name__})
        for sid in ids:
            heartbeat(db, name, owner)
            try:
                s = db.get(Signal, sid)
                evaluation = evaluate_signal(
                    db, s, cfg, market_regime(candles, s.created_at, cfg)
                )
                quote = quotes.get(s.symbol)
                if not ledger.valid_quote(quote, cfg, ledger.now_utc()):
                    try:
                        quote = market_quote(client, s.symbol)
                    except Exception:
                        quote = None
                status = ledger.process_one(db, run_id, sid, evaluation, quote)
                result[status] = result.get(status, 0) + 1
                event = (
                    db.query(V3Processing)
                    .filter_by(signal_id=sid, shadow_version=run.version)
                    .first()
                )
                if event:
                    try:
                        queue_high_value(db, run, event)
                    except Exception as exc:
                        quality_event(
                            db,
                            "notification_queue_failure",
                            {"exception": type(exc).__name__},
                        )
            except Exception as exc:
                result["errors"] += 1
                quality_event(
                    db,
                    "shadow_processing_failure",
                    {"signal_id": sid, "exception": type(exc).__name__},
                )
        # Funding retrieval is bounded to positions/trades in this run, never to V1 history.
        for symbol in {
            r[0] for r in db.query(V3Trade.symbol).filter_by(run_id=run_id).distinct()
        }:
            heartbeat(db, name, owner)
            try:
                last = (
                    db.query(func.max(V3Action.created_at))
                    .join(V3Trade, V3Action.trade_id == V3Trade.id)
                    .filter(
                        V3Action.run_id == run_id,
                        V3Action.action == "FUNDING",
                        V3Trade.symbol == symbol,
                    )
                    .scalar()
                )
                start = max(
                    run.cutover_at,
                    (last - timedelta(hours=1)) if last else run.cutover_at,
                )
                rates = client.post_info(
                    {
                        "type": "fundingHistory",
                        "coin": symbol,
                        "startTime": int(
                            start.replace(tzinfo=timezone.utc).timestamp() * 1000
                        ),
                    },
                    weight=20,
                )
                ledger.apply_funding(db, run_id, symbol, rates)
            except Exception as exc:
                quality_event(
                    db,
                    "funding_unavailable",
                    {"exception": type(exc).__name__},
                    symbol=symbol,
                )
        for (wid,) in db.query(Wallet.id).filter_by(status="active").all():
            e = (
                db.query(V3WalletEvaluation)
                .filter_by(wallet_id=wid)
                .order_by(V3WalletEvaluation.as_of.desc())
                .first()
            )
            if not e or (ledger.now_utc() - ledger.utc(e.as_of)).total_seconds() > 3600:
                heartbeat(db, name, owner)
                evaluate_wallet(db, wid, ledger.now_utc(), cfg)
        update_lifecycle(db, run, cfg)
        queue_lifecycle(db, run)
        check = ledger.reconcile(db, run_id)
        if not check["ok"]:
            raise RuntimeError("V3 accounting reconciliation failed")
        result["notifications"] = send_pending(db)
        finish(
            db,
            name,
            owner,
            result,
            "warning" if result["errors"] or result["retry"] else "ok",
        )
        write_log(
            db,
            level="info",
            module="v3_shadow",
            message="V3 cycle completed",
            payload=result,
        )
        return result
    except Exception as exc:
        if owner:
            finish(db, name, owner, {"exception": type(exc).__name__}, "failed")
        raise
    finally:
        if own:
            db.close()


class SeedLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.addresses = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        match = re.fullmatch(
            r"/wallet/(0x[a-fA-F0-9]{40})/?", dict(attrs).get("href", "")
        )
        if match:
            self.addresses.append(match[1].lower())


def discover():
    """Daily bounded discovery into candidates only, using the existing vetted import service."""
    from app.services.discovery_service import import_candidates
    from app.models.discovery import DiscoveryCandidate

    with SessionLocal() as db:
        owner = acquire(db, "v3_seed_discovery")
        if not owner:
            return
        try:
            s = get_settings()
            response = httpx.get(s.v3_discovery_url, timeout=20)
            response.raise_for_status()
            parser = SeedLinks()
            parser.feed(response.text)
            addresses = list(dict.fromkeys(parser.addresses))
            if not addresses:
                raise ValueError("No Hyperliquid trader links in source")
            known = {a.lower() for a, in db.query(DiscoveryCandidate.address)} | {
                a.lower() for a, in db.query(Wallet.address)
            }
            fresh = [a for a in addresses if a not in known]
            result = import_candidates(
                db, {a: "freedomcore_v3" for a in fresh[: s.v3_discovery_limit]}
            )
            finish(db, "v3_seed_discovery", owner, result)
        except Exception as exc:
            quality_event(db, "seed_source_failure", {"exception": type(exc).__name__})
            finish(
                db,
                "v3_seed_discovery",
                owner,
                {"exception": type(exc).__name__},
                "warning",
            )
