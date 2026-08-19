# DeepSeek Handoff Prompt (EN) — TBX Trade Terminal → Real-Deposit Readiness

> Paste the block below into DeepSeek **in Plan mode** with repository access.
> It instructs the model to investigate and produce a plan first, then switch to
> Build mode and implement. Русская версия: `DEEPSEEK_GO_LIVE_PROMPT.md`.

---

```
You are a Senior Backend Engineer with crypto-fintech experience. You are taking
over "TBX Trade Terminal" — a Smart Money Concepts (SMC) trading system for crypto
markets. Your goal: bring it to a state where the owner can safely test it with a
small REAL deposit ($200-500).

Work in two phases. Do NOT write code during Phase 1.

===============================================================================
PHASE 1 — PLAN MODE (investigate first, no code changes)
===============================================================================

Read the codebase and produce a written plan. Specifically:

1. Read these files in full before planning anything:
   - Desktop/Cryptobot/backend/app/services/strategies/smc.py     (signal engine core)
   - Desktop/Cryptobot/backend/app/services/strategies/base.py    (backtest engine)
   - Desktop/Cryptobot/backend/app/services/market_data/collector.py
   - Desktop/Cryptobot/backend/app/services/market_context/engine.py
   - Desktop/Cryptobot/backend/app/api/v1/signals.py              (execution path)
   - Desktop/Cryptobot/backend/app/services/scheduler.py
   - Desktop/Cryptobot/backend/app/models/trade.py
   - Desktop/Cryptobot/CLAUDE_FABLE_AUDIT_REPORT.md               (prior audit)

2. Verify the current state yourself rather than trusting this prompt:
   - run `cd Desktop/Cryptobot/backend && python -m pytest tests/ -q`
     (expected: 48 passing)
   - confirm `python -c "from app.main import app"` imports cleanly
   - list the alembic migrations present (expected: through 006_mvp_hardening)

3. Answer these questions in your plan, with file:line references:
   - Where exactly does an order get placed, and can a position ever end up
     without a stop-loss on the exchange?
   - What happens in our database when a stop-loss fires ON the exchange?
   - Can a user connect API keys that have withdrawal permission?
   - Is there any way to stop all trading immediately?
   - Has the strategy's profitability ever been measured? On what data?

4. Deliver a plan ordered by risk, with per-task acceptance criteria and an
   estimate. Flag anything in this prompt that you believe is wrong or outdated
   after reading the code — the code is the source of truth, not this document.

Only after presenting the plan, switch to Build mode and implement it in the
order defined below.

===============================================================================
PROJECT CONTEXT
===============================================================================

Root: Desktop/Cryptobot/

backend/            Python 3.11, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, Redis 7
  app/main.py                             entrypoint; lifespan starts background tasks
  app/config.py                           pydantic-settings, all env vars
  app/core/security.py                    JWT, bcrypt, Fernet encryption of exchange keys
  app/core/database.py                    async engine; get_db commits at request end
  app/core/redis.py                       Redis client + rate_limit_check
  app/api/deps.py                         CurrentUser, ActiveSubscriber, has_active_subscription
  app/api/v1/signals.py                   signals, SSE stream, execution, positions, close
  app/api/v1/invest.py                    Smart DCA: recommendation + execution
  app/api/v1/market.py                    market context + macro calendar
  app/api/v1/users.py                     profile, exchange keys
  app/api/v1/payments.py                  CryptoCloud (USDT) + YooKassa (RUB, feature-flagged)
  app/services/strategies/smc.py          CORE: rule-based SMC engine
  app/services/strategies/base.py         honest backtest (fees, slippage, funding)
  app/services/strategies/dca_smart.py    investor DCA engine
  app/services/market_data/collector.py   Binance WebSocket collector, 17 pairs
  app/services/market_context/engine.py   BTC guide-dog, macro blackout, altseason, cycles
  app/services/scheduler.py               background asyncio loops
  app/services/notifications/broadcaster.py  Telegram signal fan-out
  app/bot/                                Telegram bot (python-telegram-bot)
  alembic/versions/                       migrations, latest is 006_mvp_hardening
  tests/                                  pytest, 48 tests, all green

frontend/           Next.js 15, TypeScript, Tailwind, PWA
  src/lib/api.ts                          API client with refresh-token flow and SSE
  src/app/page.tsx                        dashboard: signals, positions, history

infrastructure/docker-compose.yml         backend + postgres + redis

HOW THE ALGORITHM WORKS (do not break this logic):

1. The collector holds a WebSocket to Binance and receives 1h candles for 17
   liquid pairs.
2. On each closed hourly candle the engine analyses the last 500 candles.
3. It detects: swing points, breaks of structure (BOS/CHoCH), fair value gaps
   (FVG), order blocks with displacement, liquidity sweeps; it classifies the
   market regime (TREND/RANGE/CHOP) and computes a 4h higher-timeframe bias.
4. It scores confidence 0-100. A signal is emitted only when confidence >= 50
   AND the structure offers at least 3:1 reward-to-risk.
5. Gates before publishing: macro blackout (±60 min around FOMC/NFP), BTC guide
   dog (bearish structure on BOTH 4h and 1d suppresses all longs), CHOP veto.
6. Signal -> database -> Redis pub/sub -> Telegram + SSE to the dashboard.
7. The user confirms manually. The bot NEVER trades on its own — this is a
   product principle, not an implementation detail.
8. On execution: position size derives from a 2% account risk, the order is
   placed atomically with stop-loss and take-profit attached, and portfolio
   limits apply (max 5 concurrent positions, 5% daily realised-loss circuit
   breaker).

ALREADY IMPLEMENTED — DO NOT REDO:

- Fernet keys: fail-fast when ENCRYPTION_KEY is empty (otherwise every restart
  makes stored exchange keys undecryptable)
- Signal geometry: SELL take-profits are BELOW entry, BUY above; invalid
  geometry yields no signal
- Collector: all 17 pairs concurrently via asyncio.gather, in-memory candle
  buffer instead of a REST call per candle
- Billing: separate USD/RUB price books, expires_at enforcement, hourly expiry loop
- Execution: PENDING -> exchange order -> OPEN, atomic SL/TP, PnL and fees on close
- Access: /signals requires auth, free tier sees a 24h delay, Redis rate limiting
- Paper trading mode, Market Context Engine, Smart DCA, 48 tests

===============================================================================
PHASE 2 — BUILD MODE (implement in this order)
===============================================================================

--- BLOCK 1: MANDATORY BEFORE ANY REAL MONEY ---

1.1 RUN AN HONEST BACKTEST.
Write backend/scripts/run_backtest.py that:
- downloads 2 years of 1h history for every pair in TRADE_SYMBOLS (ccxt,
  paginated — one fetch_ohlcv call will not cover it)
- runs SMCStrategy.backtest() per pair
- prints a table: pair, trades, win rate, expectancy_pct, profit factor, max
  drawdown, total costs, expired (unfilled) signals
- performs walk-forward: year one for calibration, year two for validation
- writes results to CSV and JSON
Acceptance: a report showing, per pair, whether expectancy is positive AFTER
costs. Recommend removing pairs with negative expectancy from TRADE_SYMBOLS.
Report results truthfully — if the strategy loses money, say so plainly. A
truthful negative result is the most valuable output of this entire task.

1.2 BYBIT TESTNET SUPPORT.
Execution currently always hits the live exchange. Add:
- a `testnet` field on ExchangeKeySet (app/schemas/user.py) persisted with the keys
- in signals.py and invest.py, call exchange.set_sandbox_mode(True) when set
- return the testnet flag from the API; show a "TESTNET" badge in the dashboard
Acceptance: a user can connect testnet keys and trade with no real funds.

1.3 KILL SWITCH.
- a per-user `trading_enabled` flag (new column or settings model)
- POST /api/v1/trading/kill-switch to disable new entries instantly
- an option to close all open positions with market orders
- a global admin flag in Redis that blocks execution for everyone
- a red, confirm-guarded button on the dashboard
Acceptance: with the switch on, every execute call returns 403 with a clear message.

1.4 VALIDATE API KEY PERMISSIONS ON SAVE.
When Bybit keys are saved, call a private endpoint and verify:
- the key is valid (otherwise 400 with a clear error)
- the key does NOT carry withdrawal permission; if it does, return 400 and
  require the user to recreate the key without it
Acceptance: it is impossible to store a key that can withdraw funds.

1.5 SYNC POSITIONS WITH THE EXCHANGE.
Today a trade is only marked closed when the user closes it through our API. If
a stop-loss or take-profit fires ON the exchange, our row stays OPEN forever and
PnL is wrong. Add a background loop in scheduler.py (every 60s):
- for each user with open trades, call fetch_closed_orders / fetch_my_trades for
  the relevant symbols
- when a position is closed on the exchange, record exit_price, pnl, fee,
  closed_at, set status CLOSED, and notify the user on Telegram
Acceptance: an exchange-side stop-loss is reflected in history and PnL within a
minute. Decrypt API keys only inside the loop; never log them.

--- BLOCK 2: TRUST AND TRANSPARENCY ---

2.1 CHART WITH SIGNAL MARKUP.
Use lightweight-charts (TradingView, MIT licence, free).
- GET /api/v1/market/candles?symbol=X&timeframe=1h&limit=200 served from the
  Redis candle cache
- a dashboard component: candles + horizontal entry/SL/TP lines + FVG and order
  block zones read from signal.metadata
Acceptance: clicking a signal opens its chart with the markup.

2.2 PUBLIC TRACK RECORD.
- GET /api/v1/analytics/track-record: every signal over a period and its outcome
  (determined from price history: did SL or TP get hit first), plus aggregates —
  win rate, average R multiple, expectancy, breakdown per pair
- a public, read-only page on the frontend
Acceptance: the page shows honest statistics, losing signals included.

2.3 MONITORING AND ALERTS.
- GET /api/v1/health/detailed: collector status (last candle timestamp per pair),
  Redis, database, market-context freshness
- alert the admin on Telegram if the collector has been silent for over 15 minutes
- wire up Sentry when SENTRY_DSN is configured
Acceptance: stopping the collector produces an admin alert within 15 minutes.

--- BLOCK 3: LAUNCH PREPARATION ---

3.1 MERGE THE TWO TELEGRAM BOTS.
The project contains two: Desktop/Cryptobot/bot.py (2982 lines, GPT-4o + Google
Sheets, currently the working one) and backend/app/bot/ (modular, PostgreSQL).
They advertise DIFFERENT prices ($25/$199 lifetime vs $29/$79) — a real conflict.
Port referral-UID intake, CryptoCloud payment and screenshot vision analysis into
the backend bot, then retire the root bot.py. Single source of pricing:
app/models/subscription.py.

3.2 AUTOMATIC BYBIT REFERRAL VERIFICATION.
Add referral_claims(user_id, exchange, uid UNIQUE, status, deposit_usd,
verified_at). An hourly job calls the Bybit Affiliate API, confirms the UID is
bound to our affiliate account and has deposited >= $150, and only then sets
user.referred_by. This must be the ONLY place that writes referred_by — today
any arbitrary string in that field grants free access, which is a live security hole.

3.3 DEPLOYMENT.
Extend docker-compose with nginx + HTTPS (certbot), a backend healthcheck, and a
daily PostgreSQL backup to S3 with 30-day rotation. Write a README with
step-by-step deployment instructions.

===============================================================================
HARD CONSTRAINTS — NEVER VIOLATE
===============================================================================

1. The bot NEVER opens a trade without explicit user confirmation.
2. A position must NEVER exist without a stop-loss. If the exchange rejects the
   order carrying the stop, do not open the position at all.
3. NEVER log decrypted API keys, secrets or tokens.
4. Cover every change with tests. The existing 48 tests must stay green:
   cd Desktop/Cryptobot/backend && python -m pytest tests/ -q
5. Do not remove existing protections: ENCRYPTION_KEY fail-fast, the 5-position
   cap, the 5% daily loss limit, the macro blackout, the BTC gate, the 3:1 RR
   requirement.
6. Do not put neural networks or external AI into the signal engine — it stays
   deterministic. AI is only for generating human-readable explanations.
7. Every schema change gets its own alembic migration; never edit an existing one.
8. If you find a bug outside your current task, do not stay silent — report it
   separately.

===============================================================================
REPORTING FORMAT
===============================================================================

Work block by block. After each block, report:
- the files you changed
- the test run output
- what remains unverified and where the risk sits

Start with 1.1, the backtest. Until there is evidence of positive expectancy
after fees, real money must stay off the table and everything else is secondary.
```

---

## Pre-flight checklist before the first real deposit

Go through this yourself, regardless of what the model reports:

1. PR #1 is merged into `main`; run `git pull` locally.
2. `ENCRYPTION_KEY` and `SECRET_KEY` generated and set in `.env`.
3. Migrations applied: `alembic upgrade head`.
4. Backtest (1.1) run, expectancy positive after costs.
5. At least two weeks of paper trading with signals behaving as expected.
6. Verified on Bybit **testnet** (1.2): orders, stops, closes.
7. Bybit API key created **without withdrawal permission**, IP-restricted to the server.
8. First real deposit is an amount you can afford to lose entirely.
9. Risk per trade lowered to 0.5–1% for the break-in period (instead of 2%).
10. Kill switch (1.3) tested: pressing it genuinely blocks new entries.
