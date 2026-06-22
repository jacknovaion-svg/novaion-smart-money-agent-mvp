# Paper Boss Mode Live Validation Report

Generated at: 2026-06-21T23:09:19Z

Scope: live Boss Mode notification audit from the real validation database snapshot. This report does not modify Telegram templates, trading logic, Scheduler, Discovery, Ranking, Signal Engine, scoring rules, private keys, or real trading.

## Live Service Status

- API health endpoint: ok
- System health: ok
- Scheduler: running
- Readiness: true
- Telegram configured: true
- Paper trading status: ok

## Boss Mode Notification Summary

- Boss Mode sent count: 16
- Boss Mode failed count: 0
- Boss Mode daily summary sent: yes
- Latest Boss Mode notification: 2026-06-21T21:48:03.910509Z
- Daily Boss Mode report observed: 2026-06-21T08:00:01.611605Z

Boss notifications observed:

| Time UTC | Event | Trade | Symbol |
| --- | --- | ---: | --- |
| 2026-06-21T05:03:03.909093Z | open | 2 | BTC |
| 2026-06-21T05:03:04.734588Z | add | 2 | BTC |
| 2026-06-21T08:00:01.611605Z | daily summary | n/a | n/a |
| 2026-06-21T08:48:03.890682Z | close | 2 | BTC |
| 2026-06-21T12:48:03.894549Z | open | 3 | BTC |
| 2026-06-21T12:48:04.686929Z | reduce | 3 | BTC |
| 2026-06-21T13:03:03.917185Z | reduce | 3 | BTC |
| 2026-06-21T13:03:04.698105Z | close | 3 | BTC |
| 2026-06-21T14:03:03.891657Z | open | 4 | TAO |
| 2026-06-21T21:03:03.911965Z | open | 5 | BTC |
| 2026-06-21T21:03:04.693655Z | reduce | 5 | BTC |
| 2026-06-21T21:18:03.895466Z | reduce | 5 | BTC |
| 2026-06-21T21:18:04.680730Z | add | 5 | BTC |
| 2026-06-21T21:33:03.948113Z | add | 5 | BTC |
| 2026-06-21T21:33:04.727733Z | add | 5 | BTC |
| 2026-06-21T21:48:03.910509Z | reduce | 5 | BTC |

## Duplicate Notification Audit

- Confirmed duplicate paper actions by identical `signal_id + action`: 0
- Confirmed duplicate open paper trades: 0
- Confirmed duplicate Boss sends caused by the same paper action: 0 observed

Note: the current Boss Mode notification log payload contains event_type, trade_id, and symbol, but not signal_id. Multiple `add` or `reduce` notifications for the same trade_id can be valid because one open position may receive several independent add/reduce source signals. The paper action log confirms these were distinct signal actions, not duplicate processing.

## Signal Processing Latency

All processed cutover-after signals completed within one 15-minute Scheduler cycle plus normal tolerance.

Representative latencies:

| Signal | Type | Symbol | Action | Latency |
| ---: | --- | --- | --- | ---: |
| 317 | open | ZRO | paper_opened | 898.065s |
| 328 | open | BTC | paper_opened | 597.055s |
| 329 | add | BTC | paper_added | 297.789s |
| 334 | close | BTC | paper_closed | 596.949s |
| 335 | open | BTC | paper_opened | 596.749s |
| 336 | reduce | BTC | paper_reduced | 297.711s |
| 338 | close | BTC | paper_closed | 597.348s |
| 343 | open | BTC | paper_opened | 896.853s |
| 346 | add | BTC | paper_added | 297.797s |
| 349 | reduce | BTC | paper_reduced | 297.038s |

## Telegram Failure Isolation

- Live Boss Mode send failures: 0
- Paper trading affected by Telegram: no evidence
- Existing test coverage confirms Telegram send failure does not roll back paper trade database commits or alter signal status.

## Real Daily Report Validation

- Real Boss Mode daily summary sent: yes
- Time: 2026-06-21T08:00:01.611605Z
- Source: real database, `paper_trading_telegram` log
- Report payload: `{"report_date": "2026-06-21"}`

## PnL And Account Semantics

- Realized PnL source: `sum(all paper_trades.pnl)`
- Unrealized PnL source: `sum(open paper_trades.unrealized_pnl)`
- Account balance: starting balance + realized PnL
- Account equity: account balance + unrealized PnL
- Used margin: sum(open paper_trades.size_usd)
- Available funds: account equity - used margin, floored at 0 only for display/safety

Current values:

- Starting balance: $100.00
- Realized PnL: -$1.233218
- Unrealized PnL: $0.968268
- Account balance: $98.766782
- Account equity: $99.735050
- Used margin: $65.00
- Available funds: $34.735050

No evidence was found that open trade unrealized PnL is being counted into `pnl`, that reduce realized PnL is double counted, or that close overwrites prior reduce PnL in the current live records.

## Merge Conditions

- All tests passed before this live validation: yes
- At least one real Boss Mode notification succeeded: yes
- At least one real simulated daily report succeeded: yes
- No duplicate trades: yes
- No confirmed duplicate notifications from the same paper action: yes
- Telegram failures do not affect paper trading: covered by tests; no live failures observed
- Realized/unrealized PnL口径正确: yes
- Continuous runtime above 24h: yes
- Blocking production issue: none found

## Blocking Reasons

No blocking reasons for continuing Validation Week.

Do not merge to main automatically. A human confirmation should still be required before merging this feature branch.

## Next Observation Items

- Continue watching for Telegram failures during high-frequency add/reduce periods.
- Consider adding signal_id to Boss Mode notification log payload in a future small auditability patch, not during this no-new-feature validation step.
- Keep observing Hyperliquid transient retry errors; current level is non-blocking.
