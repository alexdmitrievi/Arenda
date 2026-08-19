Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: one Telegram bot instead of two.

The project carries two: `bot.py` at the project root (2982 lines, GPT-4o +
Google Sheets, currently the one in production) and `backend/app/bot/` (modular,
PostgreSQL). They advertise DIFFERENT prices — $25/$199 lifetime versus $29/$79 —
so a customer can see two prices for the same product. That is the real bug here.

- port into the backend bot: referral-UID intake, CryptoCloud payment, and
  screenshot vision analysis
- single source of pricing: `backend/app/models/subscription.py`
- keep Google Sheets read-only as an archive; do not delete historical data
- retire the root `bot.py` only after the backend bot covers everything it did

Acceptance: one bot, one price list, no lost user data.

This is the riskiest task in the queue because the old bot has live users. Plan
the migration before writing code, and say plainly what could break.
Update `deepseek/PROJECT_STATE.md`.
