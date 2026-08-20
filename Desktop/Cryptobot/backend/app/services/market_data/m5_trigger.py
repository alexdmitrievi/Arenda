"""5-minute trigger logic for 1h signals (arm-refine flow).

A 1h signal only becomes public after the 5m chart confirms it:
- confirmation: a recent 5m swing was broken in the signal direction,
  or a 5m sweep-reclaim happened in the signal direction;
- the entry is then refined to the 5m structure (better price);
- if the refined RR drops below 2:1 the signal is discarded.
"""

import pandas as pd

M5_SWING_LOOKBACK = 2
M5_CONFIRM_LOOKBACK = 36  # 3 hours of 5m bars


def _m5_swings(df: pd.DataFrame) -> list[tuple[int, float, str]]:
    """Lightweight swing points on 5m bars: (index, price, "high"|"low")."""
    swings = []
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    if n < 5:
        return swings
    lb = M5_SWING_LOOKBACK
    for i in range(lb, n - lb):
        if all(highs[i] >= highs[i - j] for j in range(1, lb + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, lb + 1)):
            swings.append((i, float(highs[i]), "high"))
        if all(lows[i] <= lows[i - j] for j in range(1, lb + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, lb + 1)):
            swings.append((i, float(lows[i]), "low"))
    return swings


def find_5m_confirmation(df5m: pd.DataFrame, direction: str,
                         lookback: int = M5_CONFIRM_LOOKBACK) -> bool:
    """True when recent 5m structure confirms the 1h signal direction."""
    window = df5m.iloc[-lookback:] if len(df5m) > lookback else df5m
    if len(window) < 6:
        return False
    swings = _m5_swings(window)
    if not swings:
        return False
    last_close = float(window["close"].iloc[-1])

    for idx, price, kind in reversed(swings):
        if direction == "BUY" and kind == "high" and last_close > price:
            return True
        if direction == "SELL" and kind == "low" and last_close < price:
            return True

    # sweep-reclaim fallback: the LAST bar pierces the extreme of the previous
    # 7 bars and closes back inside (stop-hunt signature)
    if len(window) >= 3:
        if direction == "BUY":
            prior_low = float(window["low"].iloc[-8:-1].min())
            if float(window["low"].iloc[-1]) < prior_low and last_close > prior_low:
                return True
        else:
            prior_high = float(window["high"].iloc[-8:-1].max())
            if float(window["high"].iloc[-1]) > prior_high and last_close < prior_high:
                return True
    return False


def refine_entry_5m(df5m: pd.DataFrame, direction: str,
                    base_entry: float, stop: float) -> float:
    """Pull the entry to the nearest 5m swing that improves the price.

    BUY: lowest recent 5m swing low above the stop (but below base entry).
    SELL: highest recent 5m swing high below the stop (but above base entry).
    Returns base_entry when the 5m structure offers nothing better.
    """
    swings = _m5_swings(df5m)
    if not swings:
        return base_entry
    if direction == "BUY":
        lows = [p for _, p, k in swings if k == "low" and stop < p < base_entry]
        if lows:
            return round(min(lows), 8)
    else:
        highs = [p for _, p, k in swings if k == "high" and stop > p > base_entry]
        if highs:
            return round(max(highs), 8)
    return base_entry


def refined_rr(entry: float, stop: float, tp1: float, direction: str) -> float | None:
    """Reward-to-risk of the refined entry against the first target."""
    if direction == "BUY":
        risk = entry - stop
        reward = tp1 - entry
    else:
        risk = stop - entry
        reward = entry - tp1
    if risk <= 0:
        return None
    return round(reward / risk, 3)
