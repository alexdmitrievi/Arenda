"""Honest backtest of the SMC strategy on real Binance 1h data.

Run from the backend directory:

    python -m scripts.backtest_run

Fetches 500 1h candles per trade pair from Binance (public data, no keys),
simulates the production settings (confidence >= 50, 3:1 RR) with fees,
slippage and funding, and writes a per-pair + aggregate report to
backend/reports/backtest_report.md.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.services.market_data.symbols import LOOKBACK_CANDLES, TRADE_SYMBOLS
from app.services.strategies.base import BacktestResult
from app.services.strategies.smc import SMCStrategy

logger = logging.getLogger("tbx.scripts.backtest")

REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "backtest_report.md"


def aggregate_results(results: dict[str, BacktestResult]) -> dict:
    """Merge per-pair backtest results into one portfolio-level summary."""
    trades = [t for r in results.values() for t in r.trades]
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0.0, "expectancy_pct": 0.0,
            "profit_factor": 0.0, "max_drawdown_pct": 0.0,
            "total_pnl_pct": 0.0, "costs_pct": 0.0, "expired_signals": 0,
        }
    wins = [t for t in trades if t["pnl_pct"] > 0]
    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0)) or 0.01
    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "expectancy_pct": round(sum(t["pnl_pct"] for t in trades) / len(trades), 3),
        "profit_factor": round(gross_profit / gross_loss, 2),
        "max_drawdown_pct": max(r.max_drawdown_pct for r in results.values()),
        "total_pnl_pct": round(sum(r.total_pnl_pct for r in results.values()), 2),
        "costs_pct": round(sum(r.costs_pct for r in results.values()), 2),
        "expired_signals": sum(r.expired_signals for r in results.values()),
    }


def _to_dataframe(raw: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(
        raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    return df


async def run_backtest(
    symbols: list[str] | None = None,
    min_rr_ratio: float = 3.0,
    min_confidence: int = 50,
) -> tuple[dict[str, BacktestResult], dict]:
    import ccxt.async_support as ccxt_async

    symbols = symbols or TRADE_SYMBOLS
    strategy = SMCStrategy(min_rr_ratio=min_rr_ratio, min_confidence=min_confidence)
    exchange = ccxt_async.binance({"enableRateLimit": True})
    results: dict[str, BacktestResult] = {}
    try:
        await exchange.load_markets()
        for symbol in symbols:
            try:
                raw = await exchange.fetch_ohlcv(symbol, "1h", limit=LOOKBACK_CANDLES)
                if not raw or len(raw) < 200:
                    logger.warning("Skipping %s: only %d candles", symbol, len(raw or []))
                    continue
                results[symbol] = strategy.backtest(_to_dataframe(raw), symbol)
                r = results[symbol]
                logger.info(
                    "%s: trades=%d win=%s%% expectancy=%s%% pf=%s costs=%s%% expired=%d",
                    symbol, r.total_trades, r.win_rate, r.expectancy_pct,
                    r.profit_factor, r.costs_pct, r.expired_signals,
                )
            except Exception as e:
                logger.error("Backtest failed for %s: %s", symbol, e)
    finally:
        await exchange.close()
    return results, aggregate_results(results)


def render_report(results: dict[str, BacktestResult], aggregate: dict) -> str:
    lines = [
        "# SMC Strategy — Honest Backtest Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Settings: 1h candles, confidence >= 50, min RR 3:1, fees/slippage/funding included",
        "",
        "## Aggregate",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total trades | {aggregate['total_trades']} |",
        f"| Win rate | {aggregate['win_rate']}% |",
        f"| Expectancy per trade | {aggregate['expectancy_pct']}% |",
        f"| Profit factor | {aggregate['profit_factor']} |",
        f"| Total PnL (sum of per-trade %) | {aggregate['total_pnl_pct']}% |",
        f"| Total costs paid | {aggregate['costs_pct']}% |",
        f"| Max drawdown (per pair) | {aggregate['max_drawdown_pct']}% |",
        f"| Expired signals | {aggregate['expired_signals']} |",
        "",
        "## Per pair",
        "",
        "| Symbol | Trades | Win rate | Expectancy % | PF | Costs % | Expired |",
        "|---|---|---|---|---|---|---|",
    ]
    for symbol, r in sorted(results.items()):
        lines.append(
            f"| {symbol} | {r.total_trades} | {r.win_rate}% | {r.expectancy_pct} | "
            f"{r.profit_factor} | {r.costs_pct} | {r.expired_signals} |"
        )
    return "\n".join(lines) + "\n"


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    results, aggregate = await run_backtest()
    report = render_report(results, aggregate)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
