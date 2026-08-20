# TBX Trade Terminal

Regime-aware intraday trading system on Smart Money Concepts (SMC) for crypto
futures + DCA engine for investors. Signals are rule-based and deterministic —
every signal decomposes into named factors verifiable on a chart. DeepSeek AI
only writes human-readable explanations (Variant A), never proposes levels.

**Production:** https://tvh-ru.ru · **DeepSeek Harness (dsh):** https://tvh-ru.ru:8443

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL 16 · Redis 7 ·
Next.js 15 + TypeScript + Tailwind (PWA) · python-telegram-bot · ccxt ·
Yandex Cloud VM (2 vCPU / 4 GB, Debian 12, Docker Compose).

## Current trading policy (owner decisions, 2026-08-20)

| Policy | Value |
|---|---|
| Market | **USDT-M perpetual futures, Bybit** (Cross margin, leverage 1x default, configurable) |
| Direction | **BUY only** in real execution; SELL signals stay paper-only |
| Risk per trade | **2%** of deposit |
| Position sizing | Owner's risk-calculator formula: `объём$ = депозит × риск% / стоп-зона%` (leverage-independent; e.g. $1000 × 2% / 7% = $285.71) |
| Min reward-to-risk | **2:1** (TP ladder 3R/5R/7R) |
| Liquidity gate | publish only pairs with **24h quote volume ≥ $300M on Binance** |
| Entry refinement | 1h signal armed → **5m confirmation** (BOS/sweep) within 6h → entry refined to 5m structure; refined RR < 2 → drop |
| Volume Profile | price in POC/VA zone adds +8 confidence |
| Kill switch | `POST /api/v1/admin/killswitch` (halts signals, closes all perp positions) |
| Key permissions | keys with withdrawal/transfer rights are rejected (fail-closed) |

## Signal pipeline

Binance WS (1h + 5m candles, tickers) → SMC engine (swings, BOS/CHoCH, FVG,
order blocks, liquidity sweeps, regime, 4h bias, volume profile, Fibonacci
OTE) → confidence ≥ 50 + RR ≥ 2 → gates (CHOP, macro blackout, BTC guide dog,
liquidity, kill switch) → arm → 5m confirmation → store → DeepSeek commentary →
DB → Redis → Telegram + SSE → user confirms manually → Bybit order with atomic
SL/TP → position sync loop closes trades on exchange fills.

## Repo layout

```
backend/
  app/main.py                    entrypoint; lifespan starts background tasks
  app/config.py                  all env vars (BYBIT_TESTNET, BYBIT_LEVERAGE,
                                 MIN_DAILY_VOLUME_USD, DEEPSEEK_*)
  app/services/strategies/smc.py rule-based SMC engine (+ volume profile)
  app/services/strategies/base.py honest backtest (fees, slippage, funding)
  app/services/market_data/       collector (1h/5m/4h), m5_trigger, symbols
  app/services/ai/analyst.py      DeepSeek commentary (Variant A)
  app/services/trading/           bybit helpers, execution hardening, sync,
                                  killswitch, key permissions, credentials
  app/api/v1/                     signals, invest, market, users, payments, admin
  alembic/versions/               migrations 001–007
  scripts/                        backtest runner, channel readers (t.me, telethon)
  tests/                          114 tests
frontend/                         Next.js dashboard (BUY-only view, paper/real buttons)
infrastructure/                   docker-compose (+prod), nginx, DEPLOYMENT.md, YC scripts
deepseek/                         task prompts, PROJECT_STATE.md, channel analysis
```

## Develop / test / deploy

```sh
cd backend && python -m pytest tests/ -q          # 114 tests
python -m scripts.backtest_run                    # honest backtest, 16 pairs, Binance 1h
```

Deployment and operations: `infrastructure/DEPLOYMENT.md`
(VM access, backups, kill switch, certs, known gotchas).

## Hard constraints

The bot never opens a trade without explicit user confirmation; a position must
never exist without a stop-loss; never log secrets; ENCRYPTION_KEY fail-fast;
5-position cap; 5% daily loss limit; macro blackout; BTC gate; RR ≥ 2:1;
liquidity gate ≥ $300M; no AI in the signal engine (explanations only).
