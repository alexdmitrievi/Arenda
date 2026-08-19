Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: Bybit testnet support. Execution currently always hits the live exchange,
so there is no way to rehearse with fake money.

- add a `testnet` boolean to `ExchangeKeySet` (backend/app/schemas/user.py),
  persisted alongside the encrypted keys
- in `backend/app/api/v1/signals.py` and `backend/app/api/v1/invest.py`, call
  `exchange.set_sandbox_mode(True)` when the stored keys are testnet keys
- return the testnet flag from the API
- show a clear "TESTNET" badge in the dashboard whenever it is on

Acceptance: a user can connect testnet keys and place orders with no real funds,
and can never confuse a testnet position for a real one in the UI.

Add tests. The existing suite must stay green.
Update `deepseek/PROJECT_STATE.md`.
