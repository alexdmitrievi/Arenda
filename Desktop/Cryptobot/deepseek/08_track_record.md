Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: public track record — the single most persuasive asset for marketing, and
only if it is honest.

- `GET /api/v1/analytics/track-record`: every signal over a period with its
  outcome, determined from price history (did the stop or the target get hit
  first), plus aggregates — win rate, average R multiple, expectancy, and a
  per-pair breakdown
- a public, read-only page on the frontend, no authentication

Acceptance: the page shows losing signals as prominently as winning ones. Never
filter, round or reframe the numbers to look better — if the record is bad, the
owner needs to see that before spending money on advertising.

Add tests for the outcome-resolution logic, including the case where stop and
target fall inside the same candle (resolve conservatively to the stop).
Update `deepseek/PROJECT_STATE.md`.
