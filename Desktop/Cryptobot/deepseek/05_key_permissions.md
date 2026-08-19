Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: refuse API keys that can withdraw funds. Today any valid key is accepted,
including one that lets an attacker drain the account.

When Bybit keys are saved in `backend/app/api/v1/users.py`:
- call a private endpoint to confirm the key is valid; if not, return 400 with a
  clear error rather than storing a dead key
- inspect the key's permissions; if it carries withdrawal rights, return 400 and
  instruct the user to recreate the key without them
- surface the reason in the UI, in Russian, with a short how-to

Acceptance: it is impossible to store a key that can withdraw funds.

Never log the key or the secret, in any branch, including error paths.
Add tests with a mocked exchange client.
Update `deepseek/PROJECT_STATE.md`.
