# Phase 6A Health Center

Health Center is available at:

- API: `GET /api/system/health`
- UI: `Health`

It monitors API, database, scheduler, Telegram, Hyperliquid API, Discovery, Wallet Sync and Paper Trading.

Key signals:

- `overall_status=ok`: normal
- `overall_status=warning`: continue monitoring
- `overall_status=critical`: stop internal test and investigate

Stop the 7-day internal test if:

- scheduler is stopped
- wallet sync is critical for more than 15 minutes
- Hyperliquid API error rate is high
- database query latency exceeds 2 seconds
- Telegram alerts fail repeatedly
- paper trading PnL becomes abnormal

Telegram ops alerts use cooldown:

```env
ALERT_COOLDOWN_MINUTES=60
```

Repeated alerts inside the cooldown window are logged but not resent.
