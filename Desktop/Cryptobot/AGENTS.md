# TBX Trade Terminal — context for AI coding agents

Read this file before touching anything. Task prompts live in `deepseek/`.

## Language

The project owner is a Russian speaker. **Write everything addressed to the human
in Russian**: plans, questions, progress reports, risk warnings, conclusions.
**Keep in English**: source code, identifiers, comments, docstrings, commit
messages, PR titles/bodies, log and error strings, file paths. Technical terms
with no natural Russian equivalent stay English inside a Russian sentence
("expectancy после комиссий", "kill switch", "stop-loss"). Never reply in English.

## What this is

A regime-aware intraday trading system built on Smart Money Concepts (SMC) for
crypto, plus a DCA engine for investors. Users see signals, confirm them
manually, and the system executes on Bybit. The signal engine is **rule-based
and deterministic — no neural networks**. That is a product principle: every
signal decomposes into named factors the user can verify on a chart.

## Stack

Python 3.11 · FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL 16 · Redis 7 ·
Next.js 15 + TypeScript + Tailwind (PWA) · python-telegram-bot · ccxt · Docker

## Layout

```
backend/
  app/main.py                              entrypoint; lifespan starts background tasks
  app/config.py                            pydantic-settings, all env vars
  app/core/security.py                     JWT, bcrypt, Fernet encryption of exchange keys
  app/core/database.py                     async engine; get_db commits at request end
  app/core/redis.py                        Redis client + rate_limit_check
  app/api/deps.py                          CurrentUser, ActiveSubscriber, has_active_subscription
  app/api/v1/signals.py                    signals, SSE stream, execution, positions, close
  app/api/v1/invest.py                     Smart DCA: recommendation + execution
  app/api/v1/market.py                     market context + macro calendar
  app/api/v1/users.py                      profile, exchange keys
  app/api/v1/payments.py                   CryptoCloud (USDT) + YooKassa (RUB, flagged off)
  app/services/strategies/smc.py           CORE: rule-based SMC engine
  app/services/strategies/base.py          honest backtest (fees, slippage, funding)
  app/services/strategies/dca_smart.py     investor DCA engine
  app/services/market_data/collector.py    Binance WebSocket collector, 17 pairs
  app/services/market_context/engine.py    BTC guide-dog, macro blackout, altseason, cycles
  app/services/scheduler.py                background asyncio loops
  app/services/notifications/broadcaster.py  Telegram signal fan-out
  app/bot/                                 Telegram bot
  alembic/versions/                        migrations, latest 006_mvp_hardening
  tests/                                   pytest — 48 tests, all green
frontend/src/lib/api.ts                    API client: refresh-token flow, SSE
frontend/src/app/page.tsx                  dashboard: signals, positions, history
infrastructure/docker-compose.yml          backend + postgres + redis
```

## How the algorithm works

1. Collector holds Binance WebSockets, receives 1h and 5m candles for 17
   liquid pairs (liquidity gate: 24h quote volume ≥ $300M on Binance).
2. On each closed hourly candle the engine analyses the last 500 candles.
3. Detects swing points, breaks of structure (BOS/CHoCH), fair value gaps (FVG),
   order blocks with displacement, liquidity sweeps, volume profile (POC/VA);
   classifies the regime (TREND/RANGE/CHOP); computes a 4h higher-timeframe bias.
4. Scores confidence 0–100. A signal requires confidence ≥ 50 **and** at least
   2:1 reward-to-risk from market structure.
5. The 1h signal is then **armed**: it goes public only after the 5m chart
   confirms it (5m BOS/sweep-reclaim within 6 hours); the entry is refined to
   the 5m structure; refined RR below 2:1 → the signal is dropped.
6. Gates before publishing: macro blackout (±60 min around FOMC/NFP); BTC guide
   dog (bearish structure on **both** 4h and 1d suppresses every long); CHOP veto;
   liquidity gate (≥ $300M daily volume); kill switch.
7. DeepSeek (Variant A) writes a human-readable explanation of each published
   signal from the same data — it never proposes levels (product principle).
8. Signal → database → Redis pub/sub → Telegram + SSE to the dashboard.
9. The user confirms manually. **The bot never trades on its own.**
10. Execution: USDT-M perpetual futures on Bybit (BUY-only for now; shorts are
    paper-only), Cross margin, leverage 1x (config), size from 2% account risk;
    order placed atomically with stop-loss and take-profit attached; portfolio
    limits — max 5 concurrent positions and a 5% daily realised-loss circuit breaker.

## Already implemented — do not redo

- Fernet keys: fail-fast when `ENCRYPTION_KEY` is empty (otherwise every restart
  makes stored exchange keys undecryptable)
- Signal geometry: SELL take-profits below entry, BUY above; invalid geometry
  yields no signal
- Collector: 17 pairs concurrently via `asyncio.gather`, in-memory candle buffer
  instead of a REST call per candle
- Billing: separate USD/RUB price books, `expires_at` enforcement, hourly expiry loop
- Execution: PENDING → exchange order → OPEN, atomic SL/TP, PnL and fees on close
- Access: `/signals` requires auth, free tier sees a 24h delay, Redis rate limiting
- Paper trading mode, Market Context Engine, Smart DCA, 48 tests

## Hard constraints — never violate

1. The bot never opens a trade without explicit user confirmation.
2. A position must never exist without a stop-loss. If the exchange rejects the
   order carrying the stop, do not open the position at all.
3. Never log decrypted API keys, secrets or tokens.
4. Cover every change with tests. The existing suite must stay green:
   `cd backend && python -m pytest tests/ -q`
5. Do not remove existing protections: `ENCRYPTION_KEY` fail-fast, the 5-position
   cap, the 5% daily loss limit, the macro blackout, the BTC gate, the 2:1 RR rule,
   the ≥ $300M liquidity gate.
6. No neural networks or external AI in the signal engine. AI is only for
   generating human-readable explanations.
7. Every schema change gets its own alembic migration; never edit an existing one.
8. Found a bug outside your task? Report it separately rather than staying silent.

## Working agreement

- One task per session. Read this file, read `deepseek/PROJECT_STATE.md` if it
  exists, do the task, update `PROJECT_STATE.md` with what changed.
- After each task report, in Russian: files changed, test output, what is still
  unverified and where the risk sits.
- Decisions that belong to the owner (which pairs to drop, whether to go live)
  are questions to ask, not calls to make.
