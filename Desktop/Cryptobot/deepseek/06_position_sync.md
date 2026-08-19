Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: sync exchange-side closes. A trade is currently marked closed only when
the user closes it through our API. When a stop-loss or take-profit fires ON the
exchange, our row stays OPEN forever and every PnL number downstream is wrong.

Add a background loop in `backend/app/services/scheduler.py`, every 60 seconds:
- for each user holding open non-paper trades, call `fetch_closed_orders` /
  `fetch_my_trades` for the relevant symbols
- when a position turns out to be closed on the exchange, record `exit_price`,
  `pnl`, `fee`, `closed_at`, set status CLOSED
- notify the user on Telegram with the outcome

Acceptance: a stop-loss that fires on the exchange shows up in history and PnL
within a minute.

Decrypt API keys only inside the loop, never log them, and make one user's
failure not abort the whole cycle.
Add tests with a mocked exchange client.
Update `deepseek/PROJECT_STATE.md`.
