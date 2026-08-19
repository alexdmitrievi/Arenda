Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: know when the system is broken before the users do.

- `GET /api/v1/health/detailed`: collector status (last candle timestamp per
  pair), Redis, database, market-context freshness
- alert the admin on Telegram when the collector has been silent for over 15
  minutes, once per incident rather than every check
- wire up Sentry when `SENTRY_DSN` is configured, and stay silent when it is not

Acceptance: stopping the collector produces exactly one admin alert within 15
minutes, and a second one when it recovers.

Update `deepseek/PROJECT_STATE.md`.
