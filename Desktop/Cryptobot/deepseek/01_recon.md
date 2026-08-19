Режим: PLAN. Код не менять.

Read `AGENTS.md` at the project root first — it holds the architecture, the
algorithm and the invariants. Follow its language rule: answer in Russian.

Your task is reconnaissance. Read these files in full:

- backend/app/services/strategies/smc.py          (signal engine core)
- backend/app/services/strategies/base.py         (backtest engine)
- backend/app/services/market_data/collector.py   (data collection)
- backend/app/api/v1/signals.py                   (execution path)
- backend/app/services/scheduler.py               (background loops)
- backend/app/models/trade.py                     (trade model)

Verify the state yourself rather than trusting any document:
- `cd backend && python -m pytest tests/ -q` (expected: 48 passing)
- `python -c "from app.main import app"` imports cleanly
- list the alembic migrations present (expected: through 006_mvp_hardening)

Then answer these five questions, each with `file:line` references:

1. Where exactly is an order placed, and can a position ever end up on the
   exchange without a stop-loss?
2. What happens in our database when a stop-loss fires ON the exchange?
3. Can a user connect API keys that carry withdrawal permission?
4. Is there any way to stop all trading immediately?
5. Has the strategy's profitability ever been measured, and on what data?

Write the results to `deepseek/PROJECT_STATE.md`: test status, migration list,
the five answers, and anything you found that contradicts `AGENTS.md` — the code
is the source of truth, not the documentation.

Do not write any other code this session. Report in Russian.
