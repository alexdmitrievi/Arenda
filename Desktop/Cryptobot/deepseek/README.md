# How to work with DeepSeek on this project

The full handoff prompt was too large for one session. Context now lives in the
repository instead of the prompt: `AGENTS.md` at the project root holds the
architecture, the algorithm, and the invariants.

Each file here is one session. Paste its contents — nothing else. Every prompt
starts by telling the model to read `AGENTS.md`, so context is never lost.

## Order

| # | File | Mode | What it produces |
|---|------|------|------------------|
| 01 | `01_recon.md` | Plan | `PROJECT_STATE.md` — verified state of the project |
| 02 | `02_backtest.md` | Build | backtest script + the profitability verdict |
| 03 | `03_testnet.md` | Build | Bybit testnet support |
| 04 | `04_kill_switch.md` | Build | emergency stop |
| 05 | `05_key_permissions.md` | Build | rejection of keys with withdrawal rights |
| 06 | `06_position_sync.md` | Build | sync of exchange-side closes |
| 07 | `07_charts.md` | Build | chart with signal markup |
| 08 | `08_track_record.md` | Build | public statistics page |
| 09 | `09_monitoring.md` | Build | health checks and alerts |
| 10 | `10_bot_merge.md` | Build | one Telegram bot instead of two |
| 11 | `11_referrals.md` | Build | automatic Bybit UID verification |
| 12 | `12_deploy.md` | Build | HTTPS, backups, deployment README |

Sessions 01–06 must be finished before any real money. 07–09 build user trust.
10–12 are launch prep.

## Rules

- **One session per file.** Start a fresh session for each; do not chain them.
- Run 01 first: everything after it relies on `PROJECT_STATE.md`.
- If a session ends mid-task, start the next one with the same file — the model
  will pick up from `PROJECT_STATE.md`.
- Sessions 03–06 are independent of each other and can be done in any order.
- Do not skip 02. Until expectancy after fees is known, the rest is decoration.
