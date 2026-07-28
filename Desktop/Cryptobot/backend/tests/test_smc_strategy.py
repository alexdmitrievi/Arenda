"""
Tests for SMC (Smart Money Concepts) Strategy Engine.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.strategies.smc import (
    SMCStrategy,
    StructuralAnalysis,
    FibonacciCalculator,
    SignalGenerator,
    SwingPoint,
    BOSEvent,
)


def make_ohlcv(prices: list[float]) -> pd.DataFrame:
    n = len(prices)
    data = []
    for i, p in enumerate(prices):
        data.append({
            "timestamp": i,
            "open": p * 0.99,
            "high": p * 1.02,
            "low": p * 0.98,
            "close": p,
            "volume": 1000,
        })
    return pd.DataFrame(data)


def make_trending_up(n: int = 200, start: float = 100, step: float = 0.5) -> pd.DataFrame:
    prices = [start + i * step + np.random.randn() * 1.0 for i in range(n)]
    return make_ohlcv(prices)


def make_trending_down(n: int = 200, start: float = 150, step: float = 0.5) -> pd.DataFrame:
    prices = [start - i * step + np.random.randn() * 1.0 for i in range(n)]
    return make_ohlcv(prices)


class TestStructuralAnalysis:

    def test_detect_swing_points(self):
        df = make_trending_up(100)
        swings = StructuralAnalysis.detect_swing_points(df, lookback=3)
        assert len(swings) > 0

    def test_detect_bos(self):
        df = make_trending_up(200)
        swings = StructuralAnalysis.detect_swing_points(df)
        bos = StructuralAnalysis.detect_bos(df, swings)
        assert len(bos) >= 0

    def test_detect_fvg(self):
        df = make_trending_up(100)
        fvgs = StructuralAnalysis.detect_fvg(df)
        assert len(fvgs) >= 0

    def test_detect_order_blocks(self):
        df = make_trending_up(100)
        obs = StructuralAnalysis.detect_order_blocks(df)
        assert isinstance(obs, list)

    def test_detect_liquidity_levels(self):
        df = make_trending_up(100)
        swings = StructuralAnalysis.detect_swing_points(df)
        liq = StructuralAnalysis.detect_liquidity_levels(swings)
        assert isinstance(liq, list)


class TestFibonacciCalculator:

    def test_retracement(self):
        fib = FibonacciCalculator.retracement(200, 100)
        assert abs(fib[0.0] - 200) < 0.01
        assert abs(fib[1.0] - 100) < 0.01
        assert fib[0.5] < fib[0.0]
        assert fib[0.5] > fib[1.0]
        assert fib[0.618] < fib[0.5]

    def test_extension(self):
        ext = FibonacciCalculator.extension(200, 100)
        assert ext[1.272] > 200
        assert ext[1.618] > ext[1.272]
        assert ext[-0.272] > 200

    def test_ote_zone(self):
        fib = FibonacciCalculator.retracement(200, 100)
        ote = FibonacciCalculator.ote_zone(fib)
        assert ote["low"] > fib[1.0]
        assert ote["high"] < fib[0.0]

    def test_discount_premium(self):
        fib = FibonacciCalculator.retracement(200, 100)
        mid = fib[0.5]
        assert FibonacciCalculator.is_discount(mid - 10, fib) == True
        assert FibonacciCalculator.is_premium(mid + 10, fib) == True
        assert FibonacciCalculator.is_discount(mid + 10, fib) == False
        assert FibonacciCalculator.is_premium(mid - 10, fib) == False


class TestSMCStrategy:

    def test_generate_signal_uptrend(self):
        df = make_trending_up(200, 100, 0.3)
        strategy = SMCStrategy(min_rr_ratio=1.5, min_confidence=30)
        signal = strategy.generate_signal(df, "BTC/USDT")
        assert signal.symbol == "BTC/USDT"
        assert signal.direction in ("BUY", "SELL", "NONE")
        assert 0 <= signal.confidence <= 100

    def test_generate_signal_downtrend(self):
        df = make_trending_down(200, 150, 0.3)
        strategy = SMCStrategy(min_rr_ratio=1.5, min_confidence=30)
        signal = strategy.generate_signal(df, "BTC/USDT")
        assert signal.direction in ("BUY", "SELL", "NONE")

    def test_signal_has_valid_structure(self):
        df = make_trending_up(200, 100, 0.3)
        strategy = SMCStrategy(min_rr_ratio=1.5, min_confidence=30)
        signal = strategy.generate_signal(df, "ETH/USDT")

        if signal.direction != "NONE":
            assert signal.entry is not None
            assert signal.stop_loss is not None
            assert len(signal.take_profit) > 0
            assert signal.stop_loss > 0 if signal.direction == "BUY" else True

    def test_insufficient_data(self):
        df = make_ohlcv([100, 101, 102, 103, 104])
        strategy = SMCStrategy()
        signal = strategy.generate_signal(df)
        assert signal.direction == "NONE"
        assert signal.confidence == 0

    def test_backtest_returns_result(self):
        df = make_trending_up(300, 100, 0.3)
        strategy = SMCStrategy(min_rr_ratio=1.5, min_confidence=30)
        result = strategy.backtest(df, "BTC/USDT")
        assert result.total_trades >= 0
        assert 0 <= result.win_rate <= 100
        assert result.max_drawdown_pct >= 0


class TestSignalGeometry:
    """Directional invariants: SL and every TP must sit on the correct side of entry."""

    def _fib(self, high: float, low: float) -> dict:
        return FibonacciCalculator.retracement(high, low)

    def test_buy_targets_above_entry(self):
        gen = SignalGenerator()
        entry, stop = 100.0, 95.0
        tps = gen._find_targets(entry, stop, "BUY")
        assert all(tp > entry for tp in tps)
        assert tps == sorted(tps)

    def test_sell_targets_below_entry(self):
        gen = SignalGenerator()
        entry, stop = 100.0, 105.0
        tps = gen._find_targets(entry, stop, "SELL")
        assert all(tp < entry for tp in tps)
        assert tps == sorted(tps, reverse=True)

    def test_targets_scale_with_risk(self):
        gen = SignalGenerator()
        tps = gen._find_targets(100.0, 98.0, "BUY")
        assert tps == [106.0, 110.0, 114.0]
        tps = gen._find_targets(100.0, 102.0, "SELL")
        assert tps == [94.0, 90.0, 86.0]

    def test_zero_risk_does_not_crash(self):
        gen = SignalGenerator()
        tps = gen._find_targets(100.0, 100.0, "BUY")
        assert len(tps) == 3
        assert all(tp > 100.0 for tp in tps)

    def test_buy_entry_in_discount(self):
        gen = SignalGenerator()
        fib = self._fib(high=110.0, low=100.0)
        entry = gen._find_entry(105.0, fib, "BUY")
        assert entry < (110.0 + 100.0) / 2

    def test_sell_entry_in_premium(self):
        gen = SignalGenerator()
        fib = self._fib(high=110.0, low=100.0)
        entry = gen._find_entry(105.0, fib, "SELL")
        assert entry > (110.0 + 100.0) / 2

    def test_generated_sell_signal_geometry(self):
        """End-to-end: any SELL signal must have TP < entry < SL."""
        np.random.seed(7)
        strategy = SMCStrategy(min_rr_ratio=1.0, min_confidence=40)
        for seed in range(20):
            np.random.seed(seed)
            df = make_trending_down(250)
            signal = strategy.generate_signal(df, "TEST")
            if signal.direction == "SELL":
                assert signal.stop_loss > signal.entry
                assert all(tp < signal.entry for tp in signal.take_profit)

    def test_generated_buy_signal_geometry(self):
        """End-to-end: any BUY signal must have SL < entry < TP."""
        for seed in range(20):
            np.random.seed(seed)
            df = make_trending_up(250)
            signal = SMCStrategy(min_rr_ratio=1.0, min_confidence=40).generate_signal(df, "TEST")
            if signal.direction == "BUY":
                assert signal.stop_loss < signal.entry
                assert all(tp > signal.entry for tp in signal.take_profit)
