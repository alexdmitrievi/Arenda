Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: emergency stop. There is currently no way to halt trading instantly.

- a per-user `trading_enabled` flag (new column or a settings model + migration)
- `POST /api/v1/trading/kill-switch` — disables new entries immediately
- an option to close all open positions with market orders
- a global admin flag in Redis that blocks execution for every user at once
- a red, confirm-guarded button in the dashboard

Acceptance: with the switch on, every execute call returns 403 with a message
the user can understand; the global flag survives a backend restart.

Add tests covering both the per-user and the global switch.
Update `deepseek/PROJECT_STATE.md`.
