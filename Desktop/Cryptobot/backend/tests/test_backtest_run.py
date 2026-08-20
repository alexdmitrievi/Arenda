"""Backtest runner: aggregate reporting over per-pair results."""

import pytest

from app.services.strategies.base import BacktestResult
from scripts.backtest_run import aggregate_results, render_report


def _result(trades, pnl: float, costs: float, dd: float, expired: int = 0) -> BacktestResult:
    wins = len([t for t in trades if t["pnl_pct"] > 0])
    return BacktestResult(
        total_trades=len(trades),
        winning_trades=wins,
        losing_trades=len(trades) - wins,
        win_rate=round(wins / len(trades) * 100, 1) if trades else 0,
        total_pnl_pct=pnl,
        profit_factor=0.0,
        max_drawdown_pct=dd,
        sharpe_ratio=0.0,
        trades=trades,
        costs_pct=costs,
        expired_signals=expired,
    )


def _trade(pnl: float) -> dict:
    return {"pnl_pct": pnl}


class TestAggregateResults:
    def test_empty_results(self):
        agg = aggregate_results({})
        assert agg["total_trades"] == 0

    def test_merges_across_pairs(self):
        results = {
            "A/USDT": _result([_trade(1.0), _trade(-0.5), _trade(2.0)], 2.5, 0.3, 1.0),
            "B/USDT": _result([_trade(-1.0)], -1.0, 0.1, 2.0, expired=3),
        }
        agg = aggregate_results(results)
        assert agg["total_trades"] == 4
        assert agg["win_rate"] == 50.0
        assert agg["expectancy_pct"] == pytest.approx(0.375)  # (1 - 0.5 + 2 - 1) / 4
        assert agg["max_drawdown_pct"] == 2.0
        assert agg["total_pnl_pct"] == 1.5
        assert agg["costs_pct"] == 0.4
        assert agg["expired_signals"] == 3

    def test_profit_factor_positive(self):
        results = {"A/USDT": _result([_trade(3.0), _trade(-1.0)], 2.0, 0.0, 0.0)}
        agg = aggregate_results(results)
        assert agg["profit_factor"] == 3.0


class TestRenderReport:
    def test_report_contains_aggregate_and_pairs(self):
        results = {"A/USDT": _result([_trade(1.0)], 1.0, 0.0, 0.0)}
        agg = aggregate_results(results)
        report = render_report(results, agg)
        assert "## Aggregate" in report
        assert "| A/USDT |" in report
        assert "Expectancy per trade" in report
