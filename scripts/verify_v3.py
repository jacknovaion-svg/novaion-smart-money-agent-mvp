"""Isolated V3 acceptance tests; never imports a production database connection."""

import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
os.environ.update(
    DATABASE_URL="sqlite://",
    SCHEDULER_ENABLED="false",
    TELEGRAM_BOT_TOKEN="",
    TELEGRAM_CHAT_ID="",
)
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings
from app.core.database import Base
from app.models import (
    wallet,
    signal,
    market_data,
    ops,
    discovery,
    system_log,
    v2_validation,
    v3,
)
from app.models.wallet import Wallet
from app.models.signal import Signal, PaperTrade
from app.models.v3 import V3Run, V3Processing, V3Position, V3Trade, V3Action, V3Equity
from app.services import v3_shadow as ledger
from app.services import (
    v3_runtime as runtime,
    v3_intelligence as intelligence,
    v3_reporting as reporting,
)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            "sqlite:///" + self.tmp.name + "/test.db",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.sessions()
        self.at = ledger.now_utc()
        self.settings = get_settings().model_copy(
            update=dict(
                v3_enabled=True,
                validation_mode=True,
                enable_live_trading=False,
                emergency_stop=True,
                shadow_v3_cutover_at=self.at.isoformat() + "Z",
                v3_starting_balance=100,
                v3_execution_delay_seconds=0,
                paper_taker_fee_rate=0.0005,
                paper_slippage_rate=0.001,
            )
        )
        self.mock = patch.object(ledger, "get_settings", return_value=self.settings)
        self.mock.start()
        self.w = Wallet(
            address="0x" + "1" * 40,
            platform="hyperliquid",
            status="active",
            name="fixture",
        )
        self.db.add(self.w)
        self.db.commit()
        self.run = ledger.ensure_run(self.db)
        self.run_id = self.run.id
        self.seq = 0

    def tearDown(self):
        self.mock.stop()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def event(self, kind="open", side="long", status="new", when=None, symbol="BTC"):
        self.seq += 1
        row = Signal(
            wallet_id=self.w.id,
            symbol=symbol,
            signal_type=kind,
            side=side,
            status=status,
            current_price=100,
            source_entry_price=100,
            source_leverage=2,
            suggested_size_usd=20,
            dedupe_key=str(self.seq),
            created_at=when or self.at + timedelta(seconds=self.seq),
        )
        self.db.add(row)
        self.db.commit()
        return row

    def quote(self, price=100):
        return dict(
            mid=price, bid=price, ask=price, observed_at=self.at + timedelta(seconds=50)
        )

    def process(self, row, price=100, action=None, db=None):
        return ledger.process_one(
            db or self.db,
            self.run_id,
            row.id,
            dict(eligible=True, side=row.side, action=action or row.signal_type),
            self.quote(price),
            self.at + timedelta(seconds=50),
        )

    def test_open(self):
        s = self.event()
        self.assertEqual(self.process(s), "processed")
        p = self.db.query(V3Position).one()
        self.assertEqual(p.state, "OPEN_LONG")
        self.assertAlmostEqual(p.margin, 20)
        self.assertAlmostEqual(p.quantity, 40 / 100.1)
        self.assertEqual(s.status, "new")

    def test_historical_and_exact_cutover_excluded(self):
        for time in [self.at - timedelta(days=2), self.at]:
            s = self.event(when=time)
            self.assertEqual(self.process(s), "historical")
        self.assertEqual(ledger.pending_ids(self.db, self.run), [])
        self.assertEqual(self.db.query(V3Processing).count(), 0)

    def test_missing_cutover_fails_closed(self):
        self.settings.shadow_v3_cutover_at = ""
        with self.assertRaises(ValueError):
            ledger.ensure_run(self.db)

    def test_old_cutover_rejected(self):
        self.settings.shadow_v3_version = "old"
        self.settings.shadow_v3_cutover_at = (self.at - timedelta(days=10)).isoformat()
        with self.assertRaises(ValueError):
            ledger.ensure_run(self.db)

    def test_restart_preserves_cutover_and_idempotency(self):
        s = self.event()
        self.process(s)
        sid = s.id
        self.db.close()
        self.db = self.sessions()
        run = ledger.ensure_run(self.db)
        self.assertEqual(run.id, self.run_id)
        self.assertEqual(self.process(self.db.get(Signal, sid)), "duplicate")
        self.assertEqual(self.db.query(V3Trade).count(), 1)

    def test_all_paper_statuses_independent(self):
        for status in ["new", "simulated", "ignored", "failed"]:
            s = self.event(status=status, symbol=status)
            self.process(s)
            self.db.refresh(s)
            self.assertEqual(s.status, status)
        self.assertEqual(self.db.query(V3Trade).count(), 4)

    def test_paper_and_shadow_independent(self):
        s = self.event()
        self.process(s)
        self.db.add(
            PaperTrade(
                signal_id=s.id,
                wallet_id=s.wallet_id,
                symbol=s.symbol,
                side=s.side,
                entry_price=100,
                size_usd=20,
                leverage=2,
                status="open",
            )
        )
        s.status = "simulated"
        self.db.commit()
        self.assertEqual(self.process(s), "duplicate")
        self.assertEqual(self.db.query(PaperTrade).count(), 1)

    def test_add_weighted_entry(self):
        self.process(self.event())
        q1 = 40 / 100.1
        self.process(self.event("add"), 110)
        p = self.db.query(V3Position).one()
        q2 = 40 / 110.11
        self.assertAlmostEqual(p.quantity, q1 + q2)
        self.assertAlmostEqual(p.average_entry, 80 / (q1 + q2))
        self.assertAlmostEqual(p.margin, 40)

    def test_orphan_add_reduce_close(self):
        for kind in ["add", "reduce", "close"]:
            s = self.event(kind)
            self.assertEqual(self.process(s), "ignored")
            self.assertEqual(
                self.db.query(V3Processing).filter_by(signal_id=s.id).one().error,
                "orphan_" + kind,
            )
        self.assertEqual(self.db.query(V3Trade).count(), 0)

    def test_two_reduces_close_cumulative(self):
        self.process(self.event())
        q = 40 / 100.1
        self.process(self.event("reduce"), 110)
        self.assertAlmostEqual(self.db.query(V3Trade).one().gross_pnl, q * 0.5 * 10)
        self.process(self.event("reduce"), 120)
        self.assertAlmostEqual(self.db.query(V3Position).one().quantity, q * 0.25)
        self.process(self.event("close"), 130)
        t = self.db.query(V3Trade).one()
        actions = self.db.query(V3Action).all()
        self.assertAlmostEqual(t.gross_pnl, q * (0.5 * 10 + 0.25 * 20 + 0.25 * 30))
        for name in ["gross_pnl", "fees", "slippage", "funding", "net_pnl"]:
            self.assertAlmostEqual(
                getattr(t, name), sum(getattr(a, name) for a in actions)
            )
        self.assertAlmostEqual(t.net_pnl, t.gross_pnl - t.fees - t.slippage - t.funding)
        a = ledger.account(self.db, self.run, self.at)
        self.assertAlmostEqual(a["realized_pnl"], t.net_pnl)
        self.assertEqual(a["unrealized_pnl"], 0)

    def test_losses_cumulative(self):
        self.process(self.event())
        self.process(self.event("reduce"), 90)
        old = self.db.query(V3Trade).one().net_pnl
        self.process(self.event("close"), 80)
        self.assertLess(self.db.query(V3Trade).one().net_pnl, old)

    def test_short_accounting(self):
        self.process(self.event(side="short"))
        self.process(self.event("reduce", side="short"), 90)
        self.process(self.event("close", side="short"), 80)
        self.assertGreater(self.db.query(V3Trade).one().net_pnl, 0)

    def test_flip_atomic_close_open(self):
        self.process(self.event())
        s = self.event(side="short")
        self.process(s, 110, action="FLIP")
        trades = self.db.query(V3Trade).order_by(V3Trade.id).all()
        self.assertEqual(
            [(t.side, t.status) for t in trades],
            [("long", "closed"), ("short", "open")],
        )
        ev = self.db.query(V3Processing).filter_by(signal_id=s.id).one()
        self.assertEqual(
            self.db.query(V3Action).filter_by(processing_id=ev.id).count(), 2
        )

    def test_flip_failure_rolls_back_both_legs(self):
        self.process(self.event())
        before = self.db.query(V3Trade).one().net_pnl
        with patch.object(ledger, "enter", return_value="insufficient_shadow_funds"):
            self.process(self.event(side="short"), 110, action="FLIP")
        self.assertEqual(self.db.query(V3Trade).count(), 1)
        self.assertEqual(self.db.query(V3Trade).one().status, "open")
        self.assertEqual(self.db.query(V3Trade).one().net_pnl, before)

    def test_fee_slip_exact(self):
        self.process(self.event())
        self.process(self.event("close"), 100)
        q = 40 / 100.1
        t = self.db.query(V3Trade).one()
        self.assertAlmostEqual(t.fees, q * (100.1 + 99.9) * 0.0005)
        self.assertAlmostEqual(t.slippage, q * 0.2)
        self.assertAlmostEqual(t.gross_pnl, 0)
        self.assertAlmostEqual(t.net_pnl, -t.fees - t.slippage)

    def test_funding_sign_and_idempotency(self):
        self.process(self.event())
        at = self.at + timedelta(hours=1)
        rates = [
            dict(
                time=int(
                    at.replace(tzinfo=__import__("datetime").timezone.utc).timestamp()
                    * 1000
                ),
                fundingRate="0.001",
            )
        ]
        ledger.apply_funding(
            self.db, self.run_id, "BTC", rates, at + timedelta(seconds=1)
        )
        first = self.db.query(V3Trade).one().net_pnl
        ledger.apply_funding(
            self.db, self.run_id, "BTC", rates, at + timedelta(seconds=2)
        )
        self.assertEqual(self.db.query(V3Trade).one().net_pnl, first)
        self.assertGreater(self.db.query(V3Trade).one().funding, 0)

    def test_total_identity_with_open_partial_position(self):
        self.process(self.event())
        self.process(self.event("reduce"), 110)
        ledger.mark_all(
            self.db,
            self.run_id,
            {"BTC": self.quote(120)},
            self.at + timedelta(seconds=50),
        )
        a = ledger.account(self.db, self.run, self.at)
        self.assertAlmostEqual(a["total_pnl"], a["realized_pnl"] + a["unrealized_pnl"])
        self.assertAlmostEqual(a["equity"], 100 + a["total_pnl"])
        self.assertGreater(a["realized_pnl"], 0)

    def test_price_failure_preserves_mark(self):
        self.process(self.event())
        p = self.db.query(V3Position).one()
        old = p.mark_price
        ledger.mark_all(self.db, self.run_id, {}, self.at + timedelta(seconds=60))
        self.db.refresh(p)
        self.assertEqual(p.mark_price, old)
        self.assertEqual(p.quality, "DEGRADED")

    def test_duplicate_reduce(self):
        self.process(self.event())
        s = self.event("reduce")
        self.process(s)
        self.process(s)
        self.assertAlmostEqual(self.db.query(V3Position).one().margin, 10)

    def test_concurrent_duplicate(self):
        s = self.event()
        sid = s.id
        self.db.rollback()

        def work(_):
            with self.sessions() as db:
                return ledger.process_one(
                    db,
                    self.run_id,
                    sid,
                    dict(action="OPEN", side="long", eligible=True),
                    self.quote(),
                    self.at + timedelta(seconds=50),
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(work, range(2)))
        self.assertCountEqual(results, ["processed", "duplicate"])
        self.assertEqual(self.db.query(V3Action).count(), 1)

    def test_batch_funds_recalculated(self):
        for i in range(6):
            self.process(self.event(symbol=str(i)))
        self.assertEqual(self.db.query(V3Trade).count(), 4)
        self.assertGreaterEqual(
            ledger.account(self.db, self.run, self.at)["available_funds_raw"], 0
        )

    def test_transaction_failure_no_half_close(self):
        self.process(self.event())
        before = self.db.query(V3Trade).one().net_pnl
        s = self.event("close")
        with patch.object(ledger, "add_action", side_effect=RuntimeError("fixture")):
            with self.assertRaises(RuntimeError):
                self.process(s, 110)
        self.assertEqual(self.db.query(V3Trade).one().status, "open")
        self.assertEqual(self.db.query(V3Trade).one().net_pnl, before)
        self.assertIsNone(self.db.query(V3Processing).filter_by(signal_id=s.id).first())

    def test_legacy_rows_unchanged_by_additive_migration(self):
        s = self.event()
        before = tuple(
            self.db.execute(
                __import__("sqlalchemy").text("SELECT * FROM signals")
            ).first()
        )
        Base.metadata.create_all(self.engine)
        after = tuple(
            self.db.execute(
                __import__("sqlalchemy").text("SELECT * FROM signals")
            ).first()
        )
        self.assertEqual(before, after)
        self.assertIn("v3_signal_processing", inspect(self.engine).get_table_names())

    def test_safety_gate(self):
        self.settings.enable_live_trading = True
        with self.assertRaises(ValueError):
            self.process(self.event())
        self.assertEqual(self.db.query(V3Trade).count(), 0)

    def test_lease_single_worker_and_recovery(self):
        first = runtime.acquire(self.db, "test")
        self.assertTrue(first)
        self.assertIsNone(runtime.acquire(self.db, "test"))
        runtime.finish(self.db, "test", first, {"ok": True})
        self.assertTrue(runtime.acquire(self.db, "test"))

    def test_true_snapshot_delta_and_price_noise(self):
        import json

        old = market_data.WalletPositionSnapshot(
            wallet_id=self.w.id,
            account_value=1000,
            positions_json=json.dumps(
                [dict(coin="BTC", signed_size=2, position_value=200)]
            ),
            created_at=self.at,
        )
        new = market_data.WalletPositionSnapshot(
            wallet_id=self.w.id,
            account_value=1000,
            positions_json=json.dumps(
                [dict(coin="BTC", signed_size=1, position_value=100)]
            ),
            created_at=self.at + timedelta(seconds=1),
        )
        self.db.add_all([old, new])
        self.db.commit()
        s = self.event("reduce", when=self.at + timedelta(seconds=2))
        s.dedupe_key = f"{self.w.id}:{new.id}:BTC:reduce"
        self.db.commit()
        context = intelligence.signal_context(self.db, s, ledger.config_values())
        self.assertTrue(context["position_change_valid"])
        self.assertEqual(context["change_pct"], 0.5)
        self.assertEqual(context["change_usd"], 100)
        new.positions_json = json.dumps(
            [dict(coin="BTC", signed_size=2, position_value=170)]
        )
        self.db.commit()
        context = intelligence.signal_context(self.db, s, ledger.config_values())
        self.assertFalse(context["position_change_valid"])

    def test_no_future_information_in_score(self):
        cfg = ledger.config_values()
        before = intelligence.evaluate_wallet(
            self.db, self.w.id, self.at, cfg, persist=False
        ).score
        self.db.add(
            market_data.WalletFill(
                wallet_id=self.w.id,
                source_trade_id="future",
                coin="BTC",
                price=100,
                size=1,
                closed_pnl=100000,
                trade_time=self.at + timedelta(days=1),
            )
        )
        self.db.commit()
        after = intelligence.evaluate_wallet(
            self.db, self.w.id, self.at, cfg, persist=False
        )
        self.assertEqual(before, after.score)
        self.assertIsNone(__import__("json").loads(after.metrics_json)["roi"])

    def test_clean_drawdown_and_gap_not_estimated(self):
        rows = [
            V3Equity(
                captured_at=self.at + timedelta(minutes=i), equity=e, quality="GOOD"
            )
            for i, e in enumerate([100, 120, 90, 110])
        ]
        self.assertEqual(reporting.drawdown(rows)["amount"], 30)
        self.assertEqual(reporting.drawdown(rows)["percent"], 25)
        rows[2].quality = "DEGRADED"
        self.assertIsNone(reporting.drawdown(rows)["amount"])

    def test_attribution_partial_pnl_and_costs(self):
        self.process(self.event())
        self.process(self.event("reduce"), 110)
        data = reporting.attribution(self.db, self.run)
        self.assertAlmostEqual(
            data["summary"]["net_realized_pnl"], self.db.query(V3Trade).one().net_pnl
        )
        self.assertEqual(data["summary"]["closed_trades"], 0)
        self.assertEqual(data["validation"]["grade"], "INSUFFICIENT DATA")
        self.assertEqual(len(data["action"]), 2)

    def test_http_notification_failure_does_not_rollback(self):
        self.process(self.event())
        self.db.add(v3.V3Notification(event_key="fixture", body="fixture"))
        self.db.commit()
        cfg = self.settings.model_copy(
            update=dict(telegram_bot_token="fixture", telegram_chat_id="fixture")
        )
        with patch.object(runtime, "get_settings", return_value=cfg), patch.object(
            runtime.httpx, "post", side_effect=RuntimeError("fixture")
        ):
            self.assertEqual(runtime.send_pending(self.db), 0)
        self.assertEqual(self.db.query(V3Trade).count(), 1)
        self.assertEqual(self.db.query(v3.V3Notification).one().status, "unknown")

    def test_notification_exactly_one_attempt(self):
        self.db.add(v3.V3Notification(event_key="fixture", body="fixture"))
        self.db.commit()
        from unittest.mock import Mock

        response = Mock()
        response.json.return_value = {"ok": True, "result": {"message_id": 10}}
        cfg = self.settings.model_copy(
            update=dict(telegram_bot_token="fixture", telegram_chat_id="fixture")
        )
        with patch.object(runtime, "get_settings", return_value=cfg), patch.object(
            runtime.httpx, "post", return_value=response
        ) as send:
            runtime.send_pending(self.db)
            runtime.send_pending(self.db)
        self.assertEqual(send.call_count, 1)

    def test_cycle_signal_to_equity_and_restart(self):
        from unittest.mock import Mock

        s = self.event(when=self.at + timedelta(microseconds=1))
        client = Mock()
        book = {
            "time": int(
                (self.at + timedelta(milliseconds=1))
                .replace(tzinfo=__import__("datetime").timezone.utc)
                .timestamp()
                * 1000
            ),
            "levels": [[{"px": "99.9", "sz": "100"}], [{"px": "100.1", "sz": "100"}]],
        }

        def info(payload, **kw):
            self.assertIn(
                payload["type"], {"l2Book", "candleSnapshot", "fundingHistory"}
            )
            return book if payload["type"] == "l2Book" else []

        client.post_info.side_effect = info

        def evaluation(db, s, cfg, regime):
            return dict(
                action="OPEN",
                side="long",
                eligible=True,
                signal_score=65,
                regime=regime,
            )

        with patch.object(
            runtime, "get_settings", return_value=self.settings
        ), patch.object(runtime, "evaluate_signal", side_effect=evaluation):
            result = runtime.cycle(self.db, client)
            second = runtime.cycle(self.db, client)
        self.assertEqual(result["processed"], 1, result)
        self.assertEqual(second["processed"], 0, second)
        self.assertEqual(self.db.query(V3Trade).count(), 1)
        self.assertGreater(self.db.query(V3Equity).count(), 0)
        self.db.refresh(s)
        self.assertEqual(s.status, "new")
        self.assertEqual(
            reporting.attribution(self.db, self.run)["funnel"]["trades"], 1
        )

    def test_scheduler_v3_replaces_legacy_worker(self):
        from app.core import scheduler as sched
        from unittest.mock import Mock

        fake = Mock()
        fake.running = False
        settings = self.settings.model_copy(
            update={
                "scheduler_enabled": True,
                "v2_alpha_validation_enabled": True,
                "shadow_trading_enabled": True,
            }
        )
        with patch.object(sched, "get_settings", return_value=settings), patch.object(
            sched, "scheduler", fake
        ):
            sched.start_scheduler()
        ids = [call.kwargs["id"] for call in fake.add_job.call_args_list]
        self.assertEqual(ids.count("v3_shadow_processor"), 1)
        self.assertNotIn("v2_shadow_trade_processor", ids)
        self.assertIn("paper_trade_update", ids)

    def test_configuration_frozen_on_restart(self):
        self.settings.v3_margin_usd = 21
        with self.assertRaises(ValueError):
            ledger.ensure_run(self.db)

    def test_no_secret_or_generic_addresses_imported(self):
        parser = runtime.SeedLinks()
        parser.feed(
            '<a href="/wallet/0x'
            + "2" * 40
            + '">trader</a><a href="/token/0x'
            + "3" * 40
            + '">asset</a>'
        )
        self.assertEqual(parser.addresses, ["0x" + "2" * 40])

    def test_legacy_processor_disabled_in_v3(self):
        from app.services import v2_validation_service as old

        s = self.event()
        with patch.object(old, "get_settings", return_value=self.settings):
            self.assertEqual(
                old.process_new_signals_for_shadow(self.db)["processed"], 0
            )
            with self.assertRaises(ValueError):
                old.create_shadow_trade(self.db, s)
        self.db.refresh(s)
        self.assertEqual(s.status, "new")

    def test_action_ledger_reconstructs_position_and_balance(self):
        self.process(self.event())
        self.process(self.event("add"), 110)
        self.process(self.event("reduce"), 120)
        self.process(self.event("close"), 130)
        self.assertTrue(ledger.reconcile(self.db, self.run_id)["ok"])
        attribution = reporting.attribution(self.db, self.run)
        self.assertAlmostEqual(
            sum(a["net_pnl"] for a in attribution["entry_action"]),
            attribution["summary"]["net_realized_pnl"],
        )

    def test_excess_spread_rejected(self):
        s = self.event()
        quote = self.quote()
        quote.update(bid=90, ask=110)
        status = ledger.process_one(
            self.db,
            self.run_id,
            s.id,
            dict(action="OPEN", side="long", eligible=True),
            quote,
            self.at + timedelta(seconds=50),
        )
        self.assertEqual(status, "ignored")
        self.assertEqual(self.db.query(V3Trade).count(), 0)

    def test_short_funding_credit(self):
        self.process(self.event(side="short"))
        at = self.at + timedelta(hours=1)
        rates = [
            dict(
                time=int(
                    at.replace(tzinfo=__import__("datetime").timezone.utc).timestamp()
                    * 1000
                ),
                fundingRate="0.001",
            )
        ]
        ledger.apply_funding(
            self.db, self.run_id, "BTC", rates, at + timedelta(seconds=1)
        )
        self.assertLess(self.db.query(V3Trade).one().funding, 0)

    def test_rate_queue_covers_retry_attempts(self):
        from app.services import hyperliquid_client as client
        from unittest.mock import Mock

        fake = Mock()
        fake.__enter__ = Mock(return_value=fake)
        fake.__exit__ = Mock(return_value=False)
        fake.post.side_effect = [RuntimeError("fixture"), Mock(json=lambda: {"ok": 1})]
        with patch.object(
            client, "get_settings", return_value=self.settings
        ), patch.object(client.httpx, "Client", return_value=fake), patch.object(
            client, "_v3_request_slot"
        ) as slot, patch.object(
            client.time, "sleep"
        ), patch.object(
            client, "write_log"
        ), patch.object(
            client, "record_hyperliquid_metric"
        ):
            self.assertEqual(
                client.HyperliquidApiClient(self.db).post_info({"type": "allMids"}),
                {"ok": 1},
            )
        self.assertEqual(slot.call_count, 2)

    def test_same_version_cutover_cannot_move(self):
        self.settings.shadow_v3_cutover_at = (
            self.at + timedelta(seconds=1)
        ).isoformat() + "Z"
        with self.assertRaises(ValueError):
            ledger.ensure_run(self.db)

    def test_old_close_cannot_close_newer_open(self):
        old = self.event("close")
        new = self.event("open")
        self.process(new)
        self.assertEqual(self.process(old), "ignored")
        event = self.db.query(V3Processing).filter_by(signal_id=old.id).one()
        self.assertEqual(event.error, "out_of_order_signal")
        self.assertEqual(self.db.query(V3Trade).one().status, "open")

    def test_ingestion_after_asof_is_excluded(self):
        self.db.add(
            market_data.WalletFill(
                wallet_id=self.w.id,
                source_trade_id="late",
                coin="BTC",
                price=100,
                size=1,
                closed_pnl=100000,
                trade_time=self.at - timedelta(hours=1),
                created_at=self.at + timedelta(hours=1),
            )
        )
        self.db.commit()
        e = intelligence.evaluate_wallet(
            self.db, self.w.id, self.at, ledger.config_values(), persist=False
        )
        self.assertEqual(__import__("json").loads(e.metrics_json)["trade_count"], 0)

    def test_readonly_api_serialization_and_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.database import get_db
        from app.api.deps import get_current_user

        self.process(self.event())
        app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app)
        try:
            self.assertEqual(client.get("/api/v3/dashboard").status_code, 401)
            app.dependency_overrides[get_current_user] = lambda: True
            response = client.get("/api/v3/dashboard")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["attribution"]["summary"]["trades"], 1)
        finally:
            app.dependency_overrides.clear()
            client.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
