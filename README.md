# NOVAION Smart Money Agent MVP

Smart Money research and paper-following tool for internal testing. It does not connect private keys and does not place real trades.

## Current Scope

- FastAPI backend with SQLite
- JWT admin login
- Wallet watchlist CRUD
- System logs table
- React + Vite + Tailwind frontend
- Dashboard, wallets, wallet detail placeholder, signals placeholder, settings placeholder
- Docker Compose deployment
- Hyperliquid public info endpoint client
- Read-only sync for fills, clearinghouse state, positions and open orders
- Wallet metrics and Dashboard ranking
- APScheduler jobs for wallet sync and metrics recalculation
- Signal quality evaluation, daily internal-test report and paper-trading dashboard
- Wallet Discovery Engine candidate pool, scoring and recommended watchlist import

## Test Account

- Email: `admin@novaion.ai`
- Password: `Novaion@123`

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Web: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

Run an API smoke test after the stack is up:

```bash
python3 scripts/smoke_test.py
```

The smoke test checks health, login, wallet CRUD, dashboard, market-data read endpoints, paper account summary and logs. Use seed data to verify the full signal-to-paper-trade workflow.

Run the isolated signal and paper-trading verification:

```bash
DATABASE_URL=sqlite:///./data/novaion_full_verify.db SCHEDULER_ENABLED=false apps/api/.venv/bin/python scripts/full_verify.py
```

This synthetic test checks open/add/reduce/close signal generation, duplicate prevention, paper-trade opening, paper-trade closing, signal-quality reporting and wallet-discovery scoring.

## Local API Start

```bash
cd apps/api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
DATABASE_URL=sqlite:///./data/novaion.db .venv/bin/uvicorn app.main:app --reload
```

## No-Docker Local Start

If Docker is unavailable, run the API and the static test frontend separately:

```bash
cd apps/api
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

In another terminal:

```bash
cd apps/web-static
python3 -m http.server 5173
```

Open `http://127.0.0.1:5173`.

The static frontend defaults to API port `8010`. You can override it with `http://127.0.0.1:5173?api=http://127.0.0.1:8000`.

## API

- `POST /api/auth/login`
- `GET /api/auth/me`
- `GET /api/dashboard/summary`
- `GET /api/wallets`
- `POST /api/wallets`
- `GET /api/wallets/{wallet_id}`
- `PUT /api/wallets/{wallet_id}`
- `DELETE /api/wallets/{wallet_id}`
- `POST /api/market-data/refresh`
- `POST /api/market-data/wallets/{wallet_id}/refresh`
- `GET /api/market-data/wallets/{wallet_id}`
- `GET /api/market-data/wallet-metrics`
- `GET /api/signals`
- `GET /api/signals/{signal_id}`
- `PATCH /api/signals/{signal_id}`
- `POST /api/signals/{signal_id}/simulate`
- `GET /api/signals/paper/summary`
- `GET /api/signals/paper/trades`
- `POST /api/signals/paper/trades/{trade_id}/close`
- `GET /api/quality/dashboard`
- `GET /api/quality/daily-reports`
- `POST /api/quality/daily-reports/generate`
- `GET /api/quality/risk-rules`
- `PUT /api/quality/risk-rules`
- `GET /api/discovery/summary`
- `POST /api/discovery/run`
- `POST /api/discovery/evaluate`
- `POST /api/discovery/auto-add`
- `GET /api/discovery/candidates/{candidate_id}`
- `GET /api/system/logs`

## Database Tables

### wallets

`id`, `address`, `platform`, `name`, `tags`, `manual_score`, `status`, `notes`, `created_at`, `updated_at`

### system_logs

`id`, `level`, `module`, `message`, `payload_json`, `created_at`

### wallet_fills

Synced Hyperliquid fills. Stores normalized fields plus `raw_json` for replay/debugging.

### wallet_position_snapshots

Point-in-time clearinghouse state snapshots with normalized active positions.

### wallet_order_snapshots

Point-in-time open order snapshots.

### wallet_metrics

Calculated wallet metrics: trade counts, PnL, win rate, profit factor, current positions and last trade time.

### sync_states

Incremental sync cursor and status per wallet and sync type.

### signals

Generated smart-money signals with confidence score, risk score, suggested paper size and dedupe key.

### paper_trades

Paper-trading positions opened from signals. MVP rules cap size, leverage and risk.

### signal_performance

Post-signal quality snapshots: 5m, 15m, 1h, 4h and 24h returns, max favorable/adverse move, stop-loss and take-profit flags.

### risk_rules

Internal-test filters: wallet and symbol blacklists, whitelists, minimum wallet score, maximum leverage, minimum trades and minimum 30-day win rate. Live-trading fields remain display-only.

### daily_reports

Generated internal-test report with daily signal count, paper PnL, best/worst wallets, keep/delete suggestions and next-day focus.

### discovery_candidates

Wallet Discovery Engine candidate pool with source, score, ROI, realized/unrealized PnL, win rate, profit factor, best/worst symbols and recommendation status.

### discovery_runs

Daily discovery job history: source count, discovered count, evaluated count, auto-added count, status and error message.

## Hyperliquid Sync

The MVP only uses the public `/info` endpoint. It does not use private keys and does not place orders.

Scheduled jobs:

- Every 2 minutes: sync enabled Hyperliquid wallets
- Every 10 minutes: recalculate wallet metrics
- Daily at 02:15: run wallet discovery, candidate scoring and optional auto-add

Manual sync:

```bash
curl -X POST http://localhost:8000/api/market-data/refresh \
  -H "Authorization: Bearer <token>"
```

## Wallet Discovery Engine

Phase 5.5 adds a discovery pipeline that does not require manually adding every wallet first:

- Reads candidate wallet addresses from `DISCOVERY_SOURCE_URLS` and `DISCOVERY_LOCAL_SOURCE_PATH`.
- Evaluates candidates with Hyperliquid read-only user fills and clearinghouse state.
- Calculates candidate ROI, realized PnL, unrealized PnL, win rate, profit factor, active positions and symbol contribution.
- Scores candidates and marks high-score wallets as `recommended`.
- Optionally imports recommended wallets into the watchlist with the `auto-discovered` tag.
- Shows candidates and discovery job history in the `Discovery Center` page.

Configure sources:

```env
DISCOVERY_ENABLED=true
DISCOVERY_SOURCE_URLS=https://example.com/hyperliquid-wallets.txt
DISCOVERY_LOCAL_SOURCE_PATH=./data/discovery_wallets.txt
DISCOVERY_AUTO_ADD_ENABLED=true
DISCOVERY_MIN_SCORE_TO_ADD=70
```

Manual run:

```bash
curl -X POST http://localhost:8000/api/discovery/run \
  -H "Authorization: Bearer <token>"
```

Important limitation: Hyperliquid's `/info` API is user-address based and does not provide a simple anonymous "all active wallets" endpoint. Hyperliquid's historical node data is published separately, but the official S3 bucket is requester-pays, so anonymous local scans are blocked. For the MVP, discovery is reliable once you provide a candidate address source. Full network discovery should be added later with AWS requester-pays credentials or a maintained public data feed.

## Seed Data

```bash
cd apps/api
.venv/bin/python -m app.seed
```

This creates a demo Hyperliquid wallet, a sample signal and one paper trade.

## Paper Trading Rules

- Starting capital: 1000 USDT
- Default suggested size: 20 USDT
- Max position size: 5% of account
- Max paper leverage: 3x
- If source leverage is above 10x, paper leverage is capped at 3x
- If `risk_score > 80`, simulation is skipped
- Existing same-direction open position is not duplicated
- Live trading settings are display-only in this MVP

For local API testing without scheduler:

```bash
cd apps/api
SCHEDULER_ENABLED=false DATABASE_URL=sqlite:///./data/novaion_test.db .venv/bin/uvicorn app.main:app --reload
```

## Risk Notice

Trading is risky. This MVP is for research and simulation only. Simulated results do not represent future returns. No real trading is enabled.

## Deployment Checklist

- Change `SECRET_KEY`.
- Keep `ENABLE_LIVE_TRADING=false`.
- Keep `EMERGENCY_STOP=true`.
- Add only public wallet addresses.
- Configure Telegram only with a test chat first.
- Run `python3 scripts/smoke_test.py` after deployment.
- Confirm every page displays the risk notice or simulation-only wording before inviting testers.

## Next Phase Suggestions

- Add Alembic migrations before multi-user production testing.
- Add background job status UI and retry controls.
- Add webhook-based Telegram command acknowledgements.
- Add fees, funding and slippage to paper trading.
- Add websocket subscriptions once the polling MVP is stable.
- Add per-tester accounts only after signal and simulation quality are proven.
- Add a production-grade discovery source using Hyperliquid requester-pays historical data or an indexed public data provider.

## Known Issues

- Frontend Docker build has not been verified in this shell because Docker and npm are unavailable here.
- Metrics are based on synced fills and latest position snapshot. They are research indicators, not profitability guarantees.
- Hyperliquid first sync looks back 30 days by default. Increase `HYPERLIQUID_INITIAL_LOOKBACK_DAYS` if needed, while respecting API limits.
- Signal generation uses position snapshot comparison, so it is strongest after at least two snapshots.
- Telegram push requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- Wallet discovery needs configured candidate sources. It does not yet perform anonymous full-network Hyperliquid scans.
- No private keys or real order placement exist in this codebase.
