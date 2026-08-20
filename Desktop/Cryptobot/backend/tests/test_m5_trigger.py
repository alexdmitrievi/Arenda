"""5m trigger logic: confirmation, entry refinement, RR recheck."""

import pandas as pd
import pytest

from app.services.market_data.m5_trigger import (
    find_5m_confirmation,
    refine_entry_5m,
    refined_rr,
)


def _bars(prices: list[float], vol: float = 100.0) -> pd.DataFrame:
    rows = []
    for i, p in enumerate(prices):
        rows.append({"timestamp": i, "open": p - 0.1, "high": p + 0.4,
                     "low": p - 0.4, "close": p, "volume": vol})
    return pd.DataFrame(rows)


def _flat_then_break() -> pd.DataFrame:
    prices = [100.0] * 40
    prices += [100.1, 100.4, 100.9, 101.5, 102.0]  # breaks the flat swing high
    return _bars(prices)


class TestFind5mConfirmation:
    def test_buy_confirmed_on_swing_high_break(self):
        df = _flat_then_break()
        assert find_5m_confirmation(df, "BUY") is True

    def test_sell_not_confirmed_while_rising(self):
        df = _flat_then_break()
        assert find_5m_confirmation(df, "SELL") is False

    def test_sell_confirmed_on_drop(self):
        prices = [100.0] * 40
        prices += [99.9, 99.6, 99.1, 98.5, 98.0]
        df = _bars(prices)
        assert find_5m_confirmation(df, "SELL") is True

    def test_no_confirmation_on_flat(self):
        df = _bars([100.0] * 45)
        assert find_5m_confirmation(df, "BUY") is False

    def test_too_thin_data(self):
        assert find_5m_confirmation(_bars([100.0] * 4), "BUY") is False


class TestRefineEntry:
    def test_buy_entry_pulled_to_swing_low(self):
        prices = [100.0] * 30 + [97.0, 97.0, 97.2, 97.5, 97.4]  # swing low = candle low 96.6
        df = _bars(prices)
        entry = refine_entry_5m(df, "BUY", base_entry=99.0, stop=95.0)
        assert entry == 96.6

    def test_entry_not_pulled_below_stop(self):
        prices = [100.0] * 30 + [94.0, 94.2, 94.1]
        df = _bars(prices)
        entry = refine_entry_5m(df, "BUY", base_entry=99.0, stop=95.0)
        assert entry == 99.0  # only swing lows above the stop are eligible

    def test_sell_entry_pulled_to_swing_high(self):
        prices = [100.0] * 30 + [103.0, 103.0, 102.8, 102.5, 102.7]
        df = _bars(prices)
        entry = refine_entry_5m(df, "SELL", base_entry=101.0, stop=105.0)
        assert entry == 103.4  # swing high = candle high 103.4

    def test_no_swings_keeps_base(self):
        df = _bars([100.0] * 10)
        assert refine_entry_5m(df, "BUY", 99.0, 95.0) == 99.0


class TestRefinedRr:
    def test_buy_rr(self):
        assert refined_rr(entry=97.0, stop=95.0, tp1=103.0, direction="BUY") == 3.0

    def test_sell_rr(self):
        assert refined_rr(entry=103.0, stop=105.0, tp1=97.0, direction="SELL") == 3.0

    def test_invalid_risk_returns_none(self):
        assert refined_rr(entry=95.0, stop=95.0, tp1=100.0, direction="BUY") is None
