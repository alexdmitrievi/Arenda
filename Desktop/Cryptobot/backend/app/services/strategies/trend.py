"""
Trend Following Strategy: EMA crossover + MACD confirmation.
"""

import pandas as pd

from app.services.strategies.base import AbstractStrategy, SignalResult


class TrendStrategy(AbstractStrategy):
    name = "TREND"
    timeframe = "4h"

    def __init__(self, fast_ema: int = 9, slow_ema: int = 21):
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema

    def generate_signal(self, df: pd.DataFrame, symbol: str = "") -> SignalResult:
        if len(df) < max(self.fast_ema, self.slow_ema, 26) + 5:
            return SignalResult(symbol, "NONE", None, None, [], 0, {})

        close = df["close"]
        fast = close.ewm(span=self.fast_ema, adjust=False).mean()
        slow = close.ewm(span=self.slow_ema, adjust=False).mean()

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal_line

        current_price = float(close.iloc[-1])
        fast_val = float(fast.iloc[-1])
        slow_val = float(slow.iloc[-1])
        prev_fast = float(fast.iloc[-2])
        prev_slow = float(slow.iloc[-2])
        curr_hist = float(histogram.iloc[-1])
        prev_hist = float(histogram.iloc[-2])

        confidence = 50

        if prev_fast <= prev_slow and fast_val > slow_val:
            confidence += 20
            direction = "BUY"
        elif prev_fast >= prev_slow and fast_val < slow_val:
            confidence += 20
            direction = "SELL"
        elif fast_val > slow_val:
            direction = "BUY"
        else:
            direction = "SELL"

        if curr_hist > prev_hist and curr_hist > 0:
            confidence += 10
        elif curr_hist < prev_hist and curr_hist < 0:
            confidence += 10

        if confidence < 60:
            return SignalResult(symbol, "NONE", None, None, [], confidence, {})

        atr = float(df["high"].rolling(14).max().iloc[-1] - df["low"].rolling(14).min().iloc[-1])
        if direction == "BUY":
            entry = round(current_price, 4)
            stop = round(entry - atr * 1.5, 4)
            tp = [round(entry + atr * 3, 4), round(entry + atr * 5, 4)]
        else:
            entry = round(current_price, 4)
            stop = round(entry + atr * 1.5, 4)
            tp = [round(entry - atr * 3, 4), round(entry - atr * 5, 4)]

        return SignalResult(symbol, direction, entry, stop, tp, confidence,
                            {"ema_fast": round(fast_val, 4), "ema_slow": round(slow_val, 4)})
