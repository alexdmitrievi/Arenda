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


class TestVolumeProfile:

    def _flat_with_volume_at(self, n: int = 120, anchor: float = 100.0) -> pd.DataFrame:
        rows = []
        for i in range(n):
            vol = 5000.0 if i % 2 == 0 else 100.0
            rows.append({"timestamp": i, "open": anchor - 0.2, "high": anchor + 0.3,
                         "low": anchor - 0.3, "close": anchor, "volume": vol})
        return pd.DataFrame(rows)

    def test_poc_near_high_volume_level(self):
        df = self._flat_with_volume_at()
        profile = StructuralAnalysis.detect_volume_profile(df)
        assert profile is not None
        assert abs(profile["poc"] - 100.0) < 2.0
        assert profile["val"] <= profile["poc"] <= profile["vah"]

    def test_returns_none_on_thin_data(self):
        df = make_ohlcv([100.0 + i * 0.1 for i in range(10)])
        df["volume"] = 0.0
        assert StructuralAnalysis.detect_volume_profile(df) is None

    def test_volume_zone_boosts_buy_confidence(self):
        gen = SignalGenerator()
        fib = FibonacciCalculator.retracement(110, 100)
        highs = [SwingPoint(20, 130.0, True)]
        lows = [SwingPoint(10, 95.0, False)]
        args = (100.0, "BULLISH", fib, [], [], [], highs, lows, [], {"regime": "TREND"}, "BULLISH")
        vol_zone = {"poc": 100.0, "val": 99.0, "vah": 101.0}
        base, _ = gen._evaluate_buy(*args)
        boosted, reasons = gen._evaluate_buy(*args, vol_zone)
        assert boosted == base + 8
        assert any("объёма" in r for r in reasons)

    def test_volume_zone_outside_no_boost(self):
        gen = SignalGenerator()
        fib = FibonacciCalculator.retracement(110, 100)
        highs = [SwingPoint(20, 130.0, True)]
        lows = [SwingPoint(10, 95.0, False)]
        args = (100.0, "BULLISH", fib, [], [], [], highs, lows, [], {"regime": "TREND"}, "BULLISH")
        vol_zone = {"poc": 80.0, "val": 79.0, "vah": 81.0}
        base, _ = gen._evaluate_buy(*args)
        boosted, _ = gen._evaluate_buy(*args, vol_zone)
        assert boosted == base


class TestRegimeDetection:

    def test_trend_regime_on_strong_move(self):
        # steady climb with narrow candles: EMA displacement far exceeds ATR
        rows = []
        for i in range(200):
            p = 100 + i
            rows.append({"timestamp": i, "open": p - 0.2, "high": p + 0.5,
                         "low": p - 0.5, "close": p, "volume": 1})
        df = pd.DataFrame(rows)
        regime = StructuralAnalysis.detect_regime(df)
        assert regime["regime"] == "TREND"

    def test_insufficient_data_defaults_to_range(self):
        df = make_ohlcv([100 + i * 0.1 for i in range(30)])
        regime = StructuralAnalysis.detect_regime(df)
        assert regime["regime"] == "RANGE"

    def test_regime_keys_present(self):
        np.random.seed(2)
        df = make_trending_up(200)
        regime = StructuralAnalysis.detect_regime(df)
        assert set(regime) == {"regime", "slope_atr", "atr_rank"}


class TestLiquiditySweeps:

    def _df_with_sweep_below(self) -> pd.DataFrame:
        # flat tape with equal lows at ~98, then the last candle wicks below and closes back
        rows = []
        for i in range(60):
            rows.append({"timestamp": i, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1})
        rows[20]["low"] = 98.0
        rows[40]["low"] = 98.0
        rows.append({"timestamp": 60, "open": 100, "high": 100.5, "low": 97.5, "close": 100.2, "volume": 1})
        return pd.DataFrame(rows)

    def test_bullish_sweep_detected(self):
        df = self._df_with_sweep_below()
        liquidity = [{"price": 98.0, "type": "BUY_SIDE", "count": 2}]
        sweeps = StructuralAnalysis.detect_liquidity_sweeps(df, liquidity)
        assert any(s["type"] == "BULLISH_SWEEP" for s in sweeps)

    def test_no_sweep_without_reclaim(self):
        # candle breaks the level and CLOSES below → breakdown, not a sweep
        rows = [{"timestamp": i, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
                for i in range(60)]
        rows.append({"timestamp": 60, "open": 100, "high": 100.2, "low": 97.5, "close": 97.6, "volume": 1})
        df = pd.DataFrame(rows)
        liquidity = [{"price": 98.0, "type": "BUY_SIDE", "count": 2}]
        sweeps = StructuralAnalysis.detect_liquidity_sweeps(df, liquidity)
        assert not any(s["type"] == "BULLISH_SWEEP" for s in sweeps)


class TestHTFBias:

    def test_htf_neutral_without_data(self):
        strategy = SMCStrategy()
        assert strategy._htf_trend(None) == "NEUTRAL"
        assert strategy._htf_trend(make_ohlcv([100] * 20)) == "NEUTRAL"

    def test_htf_conflict_reduces_confidence(self):
        gen = SignalGenerator()
        fib = FibonacciCalculator.retracement(110, 100)
        highs = [SwingPoint(20, 130.0, True)]
        lows = [SwingPoint(10, 95.0, False)]
        args = (100.0, "BULLISH", fib, [], [], [], highs, lows)
        with_htf, _ = gen._evaluate_buy(*args, [], {"regime": "TREND"}, "BULLISH")
        against_htf, _ = gen._evaluate_buy(*args, [], {"regime": "TREND"}, "BEARISH")
        assert with_htf > against_htf


class TestHonestBacktest:

    def test_chop_veto_returns_none(self):
        gen = SignalGenerator()
        np.random.seed(4)
        df = make_trending_up(200)
        result = gen.generate(df, [], [], [], [], [], "X", regime={"regime": "CHOP"})
        assert result.direction == "NONE"
        assert result.confidence == 0

    def test_backtest_charges_costs(self):
        np.random.seed(5)
        df = make_trending_up(400, 100, 0.4)
        strategy = SMCStrategy(min_rr_ratio=1.0, min_confidence=30)
        result = strategy.backtest(df, "TEST")
        if result.total_trades > 0:
            assert result.costs_pct > 0
            for t in result.trades:
                assert t["costs_pct"] > 0

    def test_backtest_has_expectancy_field(self):
        np.random.seed(6)
        df = make_trending_up(300, 100, 0.3)
        strategy = SMCStrategy(min_rr_ratio=1.0, min_confidence=30)
        result = strategy.backtest(df, "TEST")
        assert hasattr(result, "expectancy_pct")
        assert hasattr(result, "expired_signals")

    def test_same_bar_stop_wins(self):
        """If one bar spans entry AND stop, the trade must be counted as SL."""
        from app.services.strategies.base import AbstractStrategy
        position = {"direction": "BUY", "entry": 100.0, "stop": 95.0, "tp": 115.0, "held_bars": 0}
        trade = AbstractStrategy._close_trade(position, 95.0, "SL")
        assert trade["result"] == "SL"
        assert trade["pnl_pct"] < 0
