Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: automatic Bybit referral verification. Right now `user.referred_by` is a
free-text field, and any non-empty value grants permanent free access — a live
security hole.

- new table `referral_claims(user_id, exchange, uid UNIQUE, status,
  deposit_usd, verified_at)` + migration
- the user submits a UID; the claim starts as `pending`
- an hourly job calls the Bybit Affiliate API, confirms the UID is bound to our
  affiliate account and has deposited at least $150, and only then sets
  `user.referred_by`
- monthly re-check of trading volume; a dead referral loses free access
- this job must be the ONLY place in the codebase that writes `referred_by`

Acceptance: a self-declared UID grants nothing until the API confirms it; one
UID can never be claimed by two accounts.

Add tests with a mocked affiliate API.
Update `deepseek/PROJECT_STATE.md`.
