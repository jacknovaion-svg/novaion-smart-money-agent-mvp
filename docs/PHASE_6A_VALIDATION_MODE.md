# Phase 6A Validation Mode

Enable 7-day validation:

```env
VALIDATION_MODE=true
VALIDATION_DAYS=7
```

Validation mode schedules:

- wallet sync every 5 minutes
- discovery every 15 minutes
- paper trade heartbeat every 15 minutes
- signal performance every 1 hour
- daily report at 08:00
- health report at 20:00

Readiness API:

```text
GET /api/validation/readiness
```

Validation can start only when:

- `wallets_count >= 5`
- `discovery_candidates_count >= 20`
- Telegram is configured
- scheduler is running
- health status is not critical

Validation dashboard:

```text
GET /api/validation/dashboard
```

Paper Trading Reality Mode:

```env
PAPER_TAKER_FEE_RATE=0.0005
PAPER_SLIPPAGE_RATE=0.001
```

The system records raw PnL, fees, slippage adjustment and net PnL. All summary statistics use net PnL.
