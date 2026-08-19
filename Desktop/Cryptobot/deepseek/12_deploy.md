Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: make the deployment survivable.

- extend `infrastructure/docker-compose.yml`: nginx with HTTPS (certbot), a
  backend healthcheck, restart policies
- daily PostgreSQL backup to S3-compatible storage with 30-day rotation, and a
  documented restore procedure that you have actually tested
- a README with step-by-step deployment: generating `ENCRYPTION_KEY` and
  `SECRET_KEY`, running `alembic upgrade head`, first launch, checking that the
  collector is alive
- a check that Binance is reachable from the server's IP — Binance restricts
  some jurisdictions, and if it is unreachable the whole product is dead;
  document the fallback to Bybit as a data source

Acceptance: a person who has never seen this project can deploy it from the
README, and a backup can be restored into an empty database.

Update `deepseek/PROJECT_STATE.md`.
