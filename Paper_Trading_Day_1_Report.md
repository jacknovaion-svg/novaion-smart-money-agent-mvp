# Paper Trading Day 1 Report

Generated at: 2026-06-21T23:09:19Z

Scope: real validation database snapshot and local live API health check. This report is observation only. No trading logic, Telegram template, Discovery, Ranking, Signal Engine, scoring rule, private key, live trading, or main branch change was performed.

## Observation Window

- Cutover UTC: 2026-06-20T05:54:35.942738Z
- Observation end UTC: 2026-06-21T23:09:19Z
- API uptime from live service: 1 day, 0:06:16

## Runtime Status

- API status: ok
- Database status: ok
- Scheduler status: running
- Telegram status: configured
- Health status: ok
- Readiness: true
- Readiness blocking reasons: none
- Health warning: none at overall level. Non-blocking heartbeat subchecks for daily cron jobs can appear old between daily runs.

## Scheduler Activity

- Wallet sync runs since cutover: 4,930
- Wallet sync failures: 0
- Paper trade update runs since cutover: 163
- Signal performance update runs since cutover: 163
- Discovery runs since cutover: 5
- Current task locks: all tracked tasks have status `ok`
- Scheduler stability: stable

## Signal Processing

- Historical `new` signals before cutover: 303
- Cutover-after signals: 47
- Eligible unprocessed new signals after cutover: 0
- Simulated signals: 16
- Ignored signals: 31
- Failed signals: 0

Signal type distribution after cutover:

- Open: 5 simulated
- Add: 4 simulated, 12 ignored
- Reduce: 5 simulated, 18 ignored
- Close: 2 simulated, 1 ignored

Ignored reasons:

- orphan_add: 10
- orphan_reduce: 13
- orphan_close: 1
- high_risk: 7
- zero_size / missing_data / insufficient funds: 0 observed in this window

## Paper Trades

- Total paper trades: 5
- Open trades: 3
- Closed trades: 2
- Price update success count: 3 open trades have non-zero mark price and updated_at
- Price update failure count: 0
- Duplicate open trades: 0

Current paper trades:

| ID | Signal | Symbol | Side | Status | Margin | Entry | Mark/Exit | PnL | Unrealized PnL |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 317 | ZRO | long | open | $20.00 | 0.90509419 | 0.91284 | $0.000000 | $0.392967 |
| 2 | 328 | BTC | long | closed | $0.00 | 64367.303 | 63883.5525 | -$1.021856 | $0.000000 |
| 3 | 335 | BTC | long | closed | $0.00 | 64009.4455 | 64004.4315 | -$0.100518 | $0.000000 |
| 4 | 339 | TAO | short | open | $20.00 | 234.33543 | 230.665 | $0.000000 | $0.820729 |
| 5 | 343 | BTC | long | open | $25.00 | 63717.654 | 63636.5 | -$0.110844 | -$0.245428 |

## Account Snapshot

- Starting balance: $100.00
- Realized PnL: -$1.233218
- Unrealized PnL: $0.968268
- Account balance: $98.766782
- Account equity: $99.735050
- Used margin: $65.00
- Available funds: $34.735050
- Account return: -0.264950%

Realized PnL check: account-level realized PnL equals `sum(all paper_trades.pnl)`, including realized reduce PnL retained on still-open trades. Open trade unrealized PnL is not counted into `pnl`.

## First Real Open Smoke Result

- First real Open signal after cutover: signal_id 317
- Symbol: ZRO
- Signal created_at: 2026-06-20T17:02:30.941780Z
- Paper opened_at: 2026-06-20T17:17:29.002576Z
- Processor action log: `paper_opened` at 2026-06-20T17:17:29.006722Z
- Processing latency: 898.065 seconds
- Entry price: 0.90509419
- Initial margin: $20.00
- Leverage: 3x
- Current mark price: 0.91284
- Current unrealized PnL: $0.392967
- Current unrealized PnL pct: 0.654945%
- Duplicate open check: no duplicate ZRO open trade found
- Current status: open

## Add / Reduce / Close Coverage

- Add appeared and was processed: yes
- Reduce appeared and was processed: yes
- Close appeared and was processed: yes
- Orphan signals were ignored, not treated as program failure: yes
- Close did not leave duplicate open BTC records: yes
- Current cumulative PnL was preserved across reduce and close paths in live records.

## Errors And Warnings

- System errors in last 24h: 4 Hyperliquid `Info request exhausted retries`
- Impact: non-blocking; Health remains ok and wallet sync / paper trading continued
- Telegram failures in this window: 0 Boss Mode failures

## Conclusion

Paper Trading Day 1 is operational. Cutover-after signals are being processed automatically, paper trades are opening/updating/reducing/closing, current prices and unrealized PnL are updating, and no duplicate paper trade creation was observed.

Validation can continue.
