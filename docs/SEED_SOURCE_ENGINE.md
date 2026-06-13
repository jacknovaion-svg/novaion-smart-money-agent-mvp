# Seed Source Engine

Phase 5.7 adds `scripts/fetch_seeds.py` to collect Hyperliquid seed wallets for Discovery.

It does not connect private keys, does not trade, and does not add wallets directly to the watchlist. It only writes candidate addresses to:

```text
apps/api/data/discovery_wallets.txt
```

Discovery Evaluation later imports and scores those candidates.

## Sources

Supported now:

- Hyperliquid Leaderboard page adapter
- Nansen Hyperliquid Leaderboard API adapter when `NANSEN_API_KEY` and `NANSEN_HYPERLIQUID_LEADERBOARD_URL` are configured
- third-party CSV/TXT/JSON URL via `--source-url` or `SEED_SOURCE_URLS`
- local CSV/TXT file via `--source-file`

Reserved adapters:

- HyperStats
- HyperTracker
- Dexly

Use their CSV/TXT exports through `--source-url` or `--source-file` until a stable API is configured.

## Ranking Window

Defaults:

- skip top 50
- fetch next 200

This targets ranks 50-250 and avoids copying only the most crowded wallets.

## Run

```bash
python3 scripts/fetch_seeds.py
```

With a third-party CSV/TXT:

```bash
python3 scripts/fetch_seeds.py --source-url https://example.com/hyperliquid-wallets.csv
```

With a local file:

```bash
python3 scripts/fetch_seeds.py --source-file ./my_seed_wallets.txt
```

## Environment

```env
NANSEN_API_KEY=
NANSEN_HYPERLIQUID_LEADERBOARD_URL=
HYPERLIQUID_LEADERBOARD_URL=https://app.hyperliquid.xyz/leaderboard
SEED_SOURCE_URLS=
SEED_SKIP_TOP=50
SEED_FETCH_LIMIT=200
SEED_OUTPUT_PATH=./apps/api/data/discovery_wallets.txt
```

If no API key is configured, the Nansen adapter is skipped without failing.

If the Hyperliquid Leaderboard page changes or renders addresses client-side, the script warns and continues. In that case use a third-party CSV/TXT export.

## Report

Every run writes:

```text
fetch_seeds_report.md
```

The report includes source status, raw address count, unique count, written count and warnings.
