Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: measure whether the strategy actually makes money.

Write `backend/scripts/run_backtest.py` that:
- downloads 2 years of 1h history for every pair in `TRADE_SYMBOLS`
  (ccxt, paginated — a single `fetch_ohlcv` call will not cover that range)
- caches the downloaded candles on disk so re-runs do not re-download
- runs `SMCStrategy.backtest()` per pair
- prints a table: pair, trades, win rate, expectancy_pct, profit factor,
  max drawdown, total costs, expired (unfilled) signals
- performs walk-forward: year one for calibration, year two for validation
- writes results to CSV and JSON under `backend/scripts/output/`

Acceptance: a report showing, per pair, whether expectancy is positive AFTER
costs, on the validation year specifically.

Report the results truthfully. If the strategy loses money, say so plainly —
a truthful negative result is the most valuable output of this whole project.
Do not tune parameters until the result looks good; that is curve-fitting and
it will lose real money later.

Then recommend which pairs to drop from `TRADE_SYMBOLS`, but do not remove them
yourself — ask the owner.

Update `deepseek/PROJECT_STATE.md` with the verdict.
