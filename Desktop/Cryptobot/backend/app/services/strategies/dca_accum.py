"""
DCA Accumulation Strategy.
Uses ATR-based dynamic allocation for DCA entries.
"""

import pandas as pd

from app.services.strategies.base import AbstractStrategy, SignalResult


class DCAStrategy(AbstractStrategy):
    name = "DCA"
    timeframe = "1d"

    def __init__(self, atr_multiplier: float = 2.0, base_allocation_pct: float = 20.0):
        self.atr_multiplier = atr_multiplier
        self.base_allocation_pct = base_allocation_pct

    def generate_signal(self, df: pd.DataFrame, symbol: str = "") -> SignalResult:
        if len(df) < 20:
            return SignalResult(symbol, "NONE", None, None, [], 0, {})

        current_price = float(df.iloc[-1]["close"])
        sma50 = float(df["close"].rolling(50).mean().iloc[-1]) if len(df) >= 50 else current_price

        high_low = df["high"] - df["low"]
        high_close = abs(df["high"] - df["close"].shift(1))
        low_close = abs(df["low"] - df["close"].shift(1))
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = float(true_range.rolling(14).mean().iloc[-1])

        deviation = (current_price - sma50) / sma50 * 100 if sma50 > 0 else 0
        alloc = self.base_allocation_pct

        if deviation < -self.atr_multiplier * (atr / sma50 * 100):
            alloc = min(self.base_allocation_pct * 1.5, 40)
            confidence = 80
        elif deviation > self.atr_multiplier * (atr / sma50 * 100):
            alloc = max(self.base_allocation_pct * 0.5, 5)
            confidence = 40
        else:
            confidence = 60

        entry = round(current_price, 4)
        stop = round(entry * 0.85, 4)
        tp = [round(entry * 1.15, 4), round(entry * 1.30, 4)]

        return SignalResult(
            symbol=symbol, direction="BUY", entry=entry,
            stop_loss=stop, take_profit=tp, confidence=confidence,
            metadata={"alloc_pct": alloc, "sma50": round(sma50, 4), "atr": round(atr, 4)},
        )
