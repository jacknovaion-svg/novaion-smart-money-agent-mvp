# NOVAION Smart Money Agent - Deployment Guide

Date: 2026-06-13
Audience: small internal test with 1 admin and 3-5 friends.

## Safety Defaults

Keep these values for internal testing:

```env
ENABLE_LIVE_TRADING=false
REQUIRE_MANUAL_APPROVAL=true
EMERGENCY_STOP=true
DISCOVERY_AUTO_ADD_ENABLED=false
```

Do not add private keys. Do not enable real trading.

## Required Environment

Copy `.env.example` to `.env` and set:

```env
SECRET_KEY=<replace-before-deploy>
ADMIN_EMAIL=admin@novaion.ai
ADMIN_PASSWORD=<replace-before-share>
DATABASE_URL=sqlite:///./data/novaion.db
TELEGRAM_BOT_TOKEN=<test-bot-token>
TELEGRAM_CHAT_ID=<test-group-chat-id>
SCHEDULER_ENABLED=true
DISCOVERY_ENABLED=true
DISCOVERY_LOCAL_SOURCE_PATH=./data/discovery_wallets.txt
DISCOVERY_AUTO_ADD_ENABLED=false
```

Optional seed adapters:

```env
NANSEN_API_KEY=
APIFY_TOKEN=
SEED_FETCH_LIMIT=200
```

## Docker Compose Start

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Web: `http://localhost:5173`
- API Docs: `http://localhost:8000/docs`

## Local No-Docker Start

API:

```bash
cd apps/api
.venv/bin/pip install -r requirements.txt
DATABASE_URL=sqlite:///./data/novaion.db SCHEDULER_ENABLED=true .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Static frontend:

```bash
cd apps/web-static
python3 -m http.server 5173
```

Open:

```text
http://127.0.0.1:5173?api=http://127.0.0.1:8000
```

## Seed Wallet Fetch

```bash
python3 scripts/fetch_seeds.py --limit 200
```

Expected current result:

- `apps/api/data/discovery_wallets.txt`
- 200 Hyperliquid wallet addresses
- `fetch_seeds_report.json`
- `fetch_seeds_report.md`

## Run Discovery / Evaluate

Use the Discovery Center in the frontend:

1. Import `apps/api/data/discovery_wallets.txt`.
2. Run Discovery.
3. Run Evaluate.
4. Review estimated metrics warnings.
5. Manually approve selected candidates into watchlist.

If API endpoints are used directly, log in first and call:

```bash
curl -X POST http://localhost:8000/api/discovery/run -H "Authorization: Bearer <token>"
curl -X POST http://localhost:8000/api/discovery/evaluate -H "Authorization: Bearer <token>"
```

## Internal Test Checklist

- `discovery_candidates_count >= 20`
- `wallets_count >= 5`
- Telegram status configured
- Scheduler status running
- Health status not critical
- Signals begin appearing
- Paper trades can be opened/closed
- Daily reports generate

## Backup

Before sharing with testers:

```bash
cp apps/api/data/novaion.db apps/api/data/novaion.backup.$(date +%Y%m%d%H%M%S).db
```

## Public Deployment Notes

For any public or semi-public deployment:

- Replace `SECRET_KEY`.
- Change default admin password.
- Put the API behind HTTPS.
- Restrict access to known testers.
- Back up SQLite daily.
- Keep Telegram pointed to a private test group.
- Keep live trading disabled.

## Current Deployment Decision

Do not start 7-day internal testing yet in the current runtime state. First import/evaluate seed wallets, approve a real watchlist, configure Telegram, and start scheduler.
