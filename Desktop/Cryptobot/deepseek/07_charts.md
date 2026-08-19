Режим: BUILD.

Read `AGENTS.md` and `deepseek/PROJECT_STATE.md` first. Answer in Russian.

Task: chart with signal markup. Traders do not trust numbers without a picture.

- `GET /api/v1/market/candles?symbol=X&timeframe=1h&limit=200`, served from the
  Redis candle cache, falling back to the exchange when the cache is cold
- a dashboard component using lightweight-charts (TradingView, MIT licence):
  candles plus horizontal entry / stop-loss / take-profit lines, plus the FVG and
  order-block zones read from `signal.metadata`
- show the signal's `reasons` list next to the chart — they are already stored
  in metadata in Russian

Acceptance: clicking a signal opens its chart with the markup, on desktop and on
a phone-sized viewport.

Update `deepseek/PROJECT_STATE.md`.
