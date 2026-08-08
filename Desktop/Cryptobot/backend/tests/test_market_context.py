"""Tests for the market-context engine and the Smart DCA engine."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.services.market_context.engine import (
    cycle_clock,
    macro_blackout,
    scheduled_macro_events,
    _nfp_dates,
)
from app.services.strategies.dca_smart import (
    MAX_MULTIPLIER,
    MIN_MULTIPLIER,
    allocation_weights,
    asset_multiplier,
    build_plan,
)


class TestMacroBlackout:

    def test_inside_fomc_window(self):
        # 30 minutes before the Jan 2026 FOMC statement
        now = datetime(2026, 1, 28, 18, 30, tzinfo=timezone.utc)
        result = macro_blackout(now)
        assert result["active"] is True
        assert "FOMC" in result["event"]

    def test_outside_any_window(self):
        now = datetime(2026, 1, 28, 12, 0, tzinfo=timezone.utc)
        result = macro_blackout(now)
        assert result["active"] is False

    def test_after_window_closes(self):
        now = datetime(2026, 1, 28, 20, 30, tzinfo=timezone.utc)
        result = macro_blackout(now)
        assert result["active"] is False

    def test_nfp_is_first_friday(self):
        for d in _nfp_dates(6):
            assert d.weekday() == 4
            assert d.day <= 7
            assert (d.hour, d.minute) == (13, 30)

    def test_extra_events_json(self):
        now = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
        extra = '[{"name": "US CPI", "at": "2026-08-12T12:30:00+00:00"}]'
        result = macro_blackout(now, extra_events_json=extra)
        assert result["active"] is True
        assert result["event"] == "US CPI"

    def test_events_sorted(self):
        events = scheduled_macro_events()
        stamps = [e["at"] for e in events]
        assert stamps == sorted(stamps)


class TestCycleClock:

    def test_phase_progression(self):
        assert cycle_clock(datetime(2024, 8, 1, tzinfo=timezone.utc))["phase"] == "post_halving_accumulation"
        assert cycle_clock(datetime(2025, 6, 1, tzinfo=timezone.utc))["phase"] == "bull_expansion"
        assert cycle_clock(datetime(2026, 7, 1, tzinfo=timezone.utc))["phase"] == "late_cycle_distribution"
        assert cycle_clock(datetime(2027, 6, 1, tzinfo=timezone.utc))["phase"] == "bear_contraction"


class TestDCAMultiplier:

    def _series(self, values: list[float]) -> pd.Series:
        return pd.Series(values, dtype=float)

    def test_deep_discount_buys_more(self):
        # long slide: price far below MA200 and >50% off the year high
        closes = self._series([100 - i * 0.15 for i in range(400)])
        multiplier, reasons = asset_multiplier(closes)
        assert multiplier > 1.0
        assert any("накопления" in r or "дисконт" in r.lower() or "просадка" in r.lower()
                   for r in reasons)

    def test_euphoria_buys_less(self):
        # parabolic run: price 2x above its long flat base
        closes = self._series([100.0] * 350 + [100 + (i + 1) * 4 for i in range(50)])
        multiplier, _ = asset_multiplier(closes)
        assert multiplier < 1.0

    def test_multiplier_bounds(self):
        crash = self._series([1000.0] * 200 + [1000 - i * 4 for i in range(200)])
        m_crash, _ = asset_multiplier(crash)
        assert MIN_MULTIPLIER <= m_crash <= MAX_MULTIPLIER

    def test_short_history_neutral(self):
        multiplier, reasons = asset_multiplier(self._series([100.0] * 30))
        assert multiplier == 1.0


class TestDCAAllocation:

    def test_weights_sum_to_one(self):
        for score in (None, 10, 50, 90):
            weights = allocation_weights(score)
            assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_altseason_tilts_to_alts(self):
        neutral = allocation_weights(50)
        altseason = allocation_weights(90)
        assert altseason["BTC/USDT"] < neutral["BTC/USDT"]
        assert altseason["ETH/USDT"] > neutral["ETH/USDT"]

    def test_btc_season_tilts_to_btc(self):
        neutral = allocation_weights(50)
        btc_season = allocation_weights(10)
        assert btc_season["BTC/USDT"] > neutral["BTC/USDT"]

    def test_build_plan_amounts(self):
        closes = {s: pd.Series([100.0] * 400) for s in
                  ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]}
        plan = build_plan(100.0, closes, altseason_score=50)
        assert len(plan) == 4
        for p in plan:
            assert p.amount_usd >= 0
            assert p.reasons
        total = sum(p.amount_usd for p in plan)
        assert abs(total - 100.0) < 1.0  # neutral market → ~1x budget
