"""
Grid Trading Strategy for ranging/flat markets.
Places buy orders at support levels and sell orders at resistance levels.
"""

import pandas as pd

from app.services.strategies.base import AbstractStrategy, SignalResult


class GridStrategy(AbstractStrategy):
    name = "GRID"
    timeframe = "1h"

    def __init__(self, grid_levels: int = 5, grid_spacing_pct: float = 1.0):
        self.grid_levels = grid_levels
        self.grid_spacing_pct = grid_spacing_pct

    def generate_signal(self, df: pd.DataFrame, symbol: str = "") -> SignalResult:
        if len(df) < 50:
            return SignalResult(symbol, "NONE", None, None, [], 0, {})

        current_price = float(df.iloc[-1]["close"])
        high = float(df["high"].rolling(50).max().iloc[-1])
        low = float(df["low"].rolling(50).min().iloc[-1])
        mid = (high + low) / 2
        range_pct = (high - low) / mid * 100 if mid > 0 else 5

        if range_pct > 15:
            return SignalResult(symbol, "NONE", None, None, [], 0,
                                {"reason": f"Range too wide ({range_pct:.1f}%), not a ranging market"})

        if current_price <= low * 1.01:
            return SignalResult(symbol, "BUY", round(current_price, 4),
                                round(low * 0.99, 4), [round(mid, 4)], 75,
                                {"grid_level": "support", "range_pct": round(range_pct, 1)})

        if current_price >= high * 0.99:
            return SignalResult(symbol, "SELL", round(current_price, 4),
                                round(high * 1.01, 4), [round(mid, 4)], 75,
                                {"grid_level": "resistance", "range_pct": round(range_pct, 1)})

        return SignalResult(symbol, "NONE", None, None, [], 10, {"range_pct": round(range_pct, 1)})
