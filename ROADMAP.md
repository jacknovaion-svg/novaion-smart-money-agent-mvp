# NOVAION Smart Money Agent - Roadmap

Date: 2026-06-13

## Principle

No new features until operational validation starts. The next phase is not product expansion; it is making the existing MVP run with real seed wallets, real signals, Telegram alerts, and paper-trading outcomes for 7 days.

## Immediate Priority

Priority 0: Run Discovery/Evaluate on the 200 real Hyperliquid seed wallets and create a real active watchlist.

Success criteria:

- At least 20 Discovery candidates imported.
- At least 5 active watchlist wallets approved.
- Telegram configured.
- Scheduler running.
- Health status no longer critical.
- First real signals and paper trades generated.

## 48-Hour Stabilization Plan

1. Import `apps/api/data/discovery_wallets.txt`.
2. Run Discovery evaluation.
3. Review candidates by score, grade, failure reason, and estimated metrics warnings.
4. Manually approve the first 5-20 wallets.
5. Configure Telegram test group.
6. Start scheduler-enabled API.
7. Verify Health Center every few hours.
8. Do not enable live trading.

## 7-Day Internal Validation Plan

Track:

- Number of generated signals.
- Open/add/reduce/close signal performance.
- Recommended wallet PnL vs baseline.
- Watch wallet PnL vs baseline.
- Best/worst wallets.
- Best/worst symbols.
- Max drawdown.
- Telegram delivery reliability.
- Paper-trade win rate and net PnL after fees/slippage.

Go/no-go after 7 days:

- Continue paper testing if signal count is low.
- Remove wallets with repeated negative contribution.
- Keep wallets with consistent positive contribution and tolerable drawdown.
- Do not enter small live testing unless simulation outperforms baseline and operational monitoring is stable.

## Deferred Work

- Real automated trading.
- Private key custody.
- Binance / OKX integrations.
- Polymarket full integration.
- Membership, billing, and payment systems.
- Complex AI agent committee.
- Mobile app.
- Public multi-user SaaS hardening.

## Before Small Live Test

Required but not part of current MVP:

- Separate real trading service.
- Private key isolation or exchange-side subaccount/API policy design.
- Manual approval workflow with audit log.
- Per-order, daily loss, and emergency stop enforcement.
- Dry-run and kill-switch tests.
- Legal/risk disclaimer review.
- Minimum 7 days of positive paper-trade evidence.

## Next Development Item After Validation Starts

Fix acceptance tooling drift: update `verify_p58_safety_patch.py` to use `--freedomcore-url` instead of the removed `--hyperliquid-leaderboard-url` argument.
