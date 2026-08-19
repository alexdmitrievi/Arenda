"""
SMC (Smart Money Concepts) Rule-Based Strategy Engine.

Replaces GPT-4o Vision analysis with mathematical OHLCV analysis.
Detects: swing points, BOS, CHoCH, FVG, Order Blocks, Liquidity levels.
Calculates Fibonacci retracement/extension zones.
Generates BUY/SELL signals with confidence scoring.
"""

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.services.strategies.base import AbstractStrategy, BacktestResult, SignalResult

logger = logging.getLogger("tbx.strategies.smc")

SWING_LOOKBACK = 5
FVG_MIN_GAP_PCT = 0.0005
LIQUIDITY_TOLERANCE_PCT = 0.001
SWEEP_LOOKBACK = 12  # candles to scan for a recent liquidity sweep
OB_DISPLACEMENT_FACTOR = 1.2  # impulse body must exceed avg body by this factor


def atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period).mean()


@dataclass
class SwingPoint:
    index: int
    price: float
    is_high: bool


@dataclass
class BOSEvent:
    index: int
    price: float
    direction: str  # "BULLISH" | "BEARISH"
    broken_swing: SwingPoint


@dataclass
class FVGZone:
    start_idx: int
    end_idx: int
    top: float
    bottom: float
    direction: str  # "BULLISH" | "BEARISH"


class StructuralAnalysis:
    @staticmethod
    def detect_swing_points(df: pd.DataFrame, lookback: int = SWING_LOOKBACK) -> list[SwingPoint]:
        swings = []
        highs = df["high"].values
        lows = df["low"].values

        for i in range(lookback, len(df) - lookback):
            is_swing_high = True
            for j in range(1, lookback + 1):
                if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                    is_swing_high = False
                    break
            if is_swing_high:
                swings.append(SwingPoint(i, float(highs[i]), True))

            is_swing_low = True
            for j in range(1, lookback + 1):
                if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                    is_swing_low = False
                    break
            if is_swing_low:
                swings.append(SwingPoint(i, float(lows[i]), False))

        return sorted(swings, key=lambda s: s.index)

    @staticmethod
    def detect_bos(df: pd.DataFrame, swings: list[SwingPoint]) -> list[BOSEvent]:
        bos_events = []
        if len(swings) < 2:
            return bos_events

        latest_bullish_bos_idx = -1
        latest_bearish_bos_idx = -1

        for i in range(len(swings) - 1):
            current = swings[i]
            if current.is_high:
                for j in range(i + 1, len(swings)):
                    future = swings[j]
                    break_price = df.iloc[current.index : future.index + 1]["close"].max()
                    if break_price > current.price and future.is_high and future.price > current.price:
                        if future.index > latest_bullish_bos_idx:
                            bos_events.append(BOSEvent(future.index, float(break_price), "BULLISH", current))
                            latest_bullish_bos_idx = future.index
                        break
            else:
                for j in range(i + 1, len(swings)):
                    future = swings[j]
                    break_price = df.iloc[current.index : future.index + 1]["close"].min()
                    if break_price < current.price and not future.is_high and future.price < current.price:
                        if future.index > latest_bearish_bos_idx:
                            bos_events.append(BOSEvent(future.index, float(break_price), "BEARISH", current))
                            latest_bearish_bos_idx = future.index
                        break

        return bos_events

    @staticmethod
    def detect_choch(df: pd.DataFrame, bos_events: list[BOSEvent]) -> list[BOSEvent]:
        choch_events = []
        last_bull_bos = None
        last_bear_bos = None

        for bos in sorted(bos_events, key=lambda b: b.index):
            if bos.direction == "BULLISH":
                if last_bear_bos is not None and bos.index > last_bear_bos.index:
                    if bos.price > last_bear_bos.price * 1.005:
                        choch_events.append(bos)
                last_bull_bos = bos
            else:
                if last_bull_bos is not None and bos.index > last_bull_bos.index:
                    if bos.price < last_bull_bos.price * 0.995:
                        choch_events.append(bos)
                last_bear_bos = bos

        return choch_events

    @staticmethod
    def detect_fvg(df: pd.DataFrame) -> list[FVGZone]:
        fvgs = []

        for i in range(1, len(df) - 1):
            prev_candle = df.iloc[i - 1]
            next_candle = df.iloc[i + 1]

            if prev_candle["low"] > next_candle["high"]:
                gap = prev_candle["low"] - next_candle["high"]
                if gap / prev_candle["low"] > FVG_MIN_GAP_PCT:
                    fvgs.append(FVGZone(
                        start_idx=i - 1, end_idx=i + 1,
                        top=float(prev_candle["low"]),
                        bottom=float(next_candle["high"]),
                        direction="BEARISH",
                    ))

            if prev_candle["high"] < next_candle["low"]:
                gap = next_candle["low"] - prev_candle["high"]
                if gap / prev_candle["high"] > FVG_MIN_GAP_PCT:
                    fvgs.append(FVGZone(
                        start_idx=i - 1, end_idx=i + 1,
                        top=float(next_candle["low"]),
                        bottom=float(prev_candle["high"]),
                        direction="BULLISH",
                    ))

        return fvgs

    @staticmethod
    def detect_order_blocks(df: pd.DataFrame) -> list[dict]:
        obs = []

        # displacement filter: the breakout candle must be a genuine impulse,
        # not an average bar, or the "order block" is just noise
        bodies = (df["close"] - df["open"]).abs()
        avg_body = bodies.rolling(14).mean()

        def has_displacement(i: int) -> bool:
            threshold = avg_body.iloc[i]
            if np.isnan(threshold) or threshold <= 0:
                return True  # not enough history to judge — keep old behaviour
            return bodies.iloc[i] >= OB_DISPLACEMENT_FACTOR * threshold

        for i in range(2, len(df) - 1):
            c_2 = df.iloc[i - 2]
            c_1 = df.iloc[i - 1]
            c_0 = df.iloc[i]

            is_bearish_c2 = c_2["close"] < c_2["open"]
            is_bullish_c1 = c_1["close"] > c_1["open"]
            impulse = c_0["high"] - c_1["close"]

            if is_bearish_c2 and is_bullish_c1 and impulse > 0:
                if c_0["close"] > c_1["high"] and has_displacement(i):
                    obs.append({
                        "index": i - 2,
                        "type": "BULLISH",
                        "high": float(c_2["high"]),
                        "low": float(c_2["low"]),
                    })

            is_bullish_c2 = c_2["close"] > c_2["open"]
            is_bearish_c1 = c_1["close"] < c_1["open"]
            impulse_down = c_1["close"] - c_0["low"]

            if is_bullish_c2 and is_bearish_c1 and impulse_down > 0:
                if c_0["close"] < c_1["low"] and has_displacement(i):
                    obs.append({
                        "index": i - 2,
                        "type": "BEARISH",
                        "high": float(c_2["high"]),
                        "low": float(c_2["low"]),
                    })

        return obs

    @staticmethod
    def detect_regime(df: pd.DataFrame) -> dict:
        """Classify the market: TREND (directional), RANGE (flat), CHOP (violent but directionless).

        Signals are suppressed in CHOP — the highest false-positive environment
        for structure-based entries.
        """
        if len(df) < 60:
            return {"regime": "RANGE", "slope_atr": 0.0, "atr_rank": 0.0}

        close = df["close"]
        ema50 = close.ewm(span=50, adjust=False).mean()
        atr = atr_series(df)
        last_atr = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0
        if last_atr <= 0:
            return {"regime": "RANGE", "slope_atr": 0.0, "atr_rank": 0.0}

        # EMA displacement over 10 bars, measured in ATR units
        slope_atr = float((ema50.iloc[-1] - ema50.iloc[-11]) / last_atr)

        atr_pct = (atr / close).dropna()
        atr_rank = float((atr_pct < atr_pct.iloc[-1]).mean()) if len(atr_pct) > 1 else 0.0

        if abs(slope_atr) >= 1.0:
            regime = "TREND"
        elif atr_rank >= 0.8 and abs(slope_atr) < 0.4:
            regime = "CHOP"
        else:
            regime = "RANGE"

        return {"regime": regime, "slope_atr": round(slope_atr, 2), "atr_rank": round(atr_rank, 2)}

    @staticmethod
    def detect_liquidity_sweeps(df: pd.DataFrame, liquidity: list[dict],
                                lookback: int = SWEEP_LOOKBACK) -> list[dict]:
        """A sweep = a wick pierces a liquidity pool but the candle closes back.

        Stops above equal highs taken then rejected → bearish setup fuel;
        stops below equal lows taken then reclaimed → bullish.
        """
        sweeps = []
        if not liquidity or len(df) < 2:
            return sweeps

        start = max(1, len(df) - lookback)
        for level in liquidity:
            price = level["price"]
            for i in range(len(df) - 1, start - 1, -1):
                candle = df.iloc[i]
                if level["type"] == "SELL_SIDE":
                    if candle["high"] > price and candle["close"] < price:
                        sweeps.append({"index": i, "price": float(price), "type": "BEARISH_SWEEP"})
                        break
                else:
                    if candle["low"] < price and candle["close"] > price:
                        sweeps.append({"index": i, "price": float(price), "type": "BULLISH_SWEEP"})
                        break

        return sweeps

    @staticmethod
    def detect_liquidity_levels(swings: list[SwingPoint]) -> list[dict]:
        liquidity = []
        high_swings = [s for s in swings if s.is_high]
        low_swings = [s for s in swings if not s.is_high]

        for i in range(len(high_swings)):
            for j in range(i + 1, len(high_swings)):
                a, b = high_swings[i], high_swings[j]
                if a.price > 0:
                    diff = abs(a.price - b.price) / a.price
                    if diff < LIQUIDITY_TOLERANCE_PCT:
                        liquidity.append({
                            "price": float((a.price + b.price) / 2),
                            "type": "SELL_SIDE",
                            "count": 2,
                        })

        for i in range(len(low_swings)):
            for j in range(i + 1, len(low_swings)):
                a, b = low_swings[i], low_swings[j]
                if a.price > 0:
                    diff = abs(a.price - b.price) / a.price
                    if diff < LIQUIDITY_TOLERANCE_PCT:
                        liquidity.append({
                            "price": float((a.price + b.price) / 2),
                            "type": "BUY_SIDE",
                            "count": 2,
                        })

        return liquidity


class FibonacciCalculator:
    RETRACEMENT_LEVELS = [0.0, 0.382, 0.5, 0.618, 0.786, 1.0]
    EXTENSION_LEVELS = [-0.272, -0.618, 1.272, 1.618]

    @staticmethod
    def retracement(high: float, low: float) -> dict[float, float]:
        diff = high - low
        return {level: round(high - diff * level, 4) for level in FibonacciCalculator.RETRACEMENT_LEVELS}

    @staticmethod
    def extension(high: float, low: float) -> dict[float, float]:
        diff = high - low
        result = {}
        for level in FibonacciCalculator.EXTENSION_LEVELS:
            if level > 1:
                result[level] = round(high + diff * (level - 1), 4)
            else:
                result[level] = round(high + diff * abs(level), 4)
        return result

    @staticmethod
    def ote_zone(fib: dict[float, float]) -> dict[str, float]:
        return {"low": fib.get(0.618, 0), "high": fib.get(0.786, 0)}

    @staticmethod
    def is_discount(price: float, fib: dict[float, float]) -> bool:
        return price < fib.get(0.5, 0)

    @staticmethod
    def is_premium(price: float, fib: dict[float, float]) -> bool:
        return price > fib.get(0.5, 0)


class SignalGenerator:
    def __init__(self, min_rr_ratio: float = 3.0, min_confidence: int = 50):
        self.min_rr_ratio = min_rr_ratio
        self.min_confidence = min_confidence

    def generate(
        self,
        df: pd.DataFrame,
        swings: list[SwingPoint],
        bos_events: list[BOSEvent],
        fvgs: list[FVGZone],
        obs: list[dict],
        liquidity: list[dict],
        symbol: str = "",
        sweeps: list[dict] | None = None,
        regime: dict | None = None,
        htf_trend: str = "NEUTRAL",
    ) -> SignalResult:
        sweeps = sweeps or []
        regime = regime or {"regime": "RANGE"}
        current_price = float(df.iloc[-1]["close"])

        trend = self._determine_trend(bos_events)

        # CHOP veto: violent, directionless tape produces the worst
        # structure-based entries — stand aside entirely
        if regime.get("regime") == "CHOP":
            return SignalResult(
                symbol=symbol, direction="NONE", entry=None, stop_loss=None,
                take_profit=[], confidence=0,
                metadata={"trend": trend, "regime": regime,
                          "reasons": ["Рынок в режиме CHOP — сигналы отключены"]},
            )

        recent_swing_highs = [s for s in swings if s.is_high and s.index > len(df) - 50]
        recent_swing_lows = [s for s in swings if not s.is_high and s.index > len(df) - 50]

        if recent_swing_highs and recent_swing_lows:
            highest = max(s.price for s in recent_swing_highs)
            lowest = min(s.price for s in recent_swing_lows)
            fib = FibonacciCalculator.retracement(highest, lowest)
        else:
            fib = FibonacciCalculator.retracement(
                float(df["high"].max()), float(df["low"].min())
            )

        buy_confidence, buy_reasons = self._evaluate_buy(
            current_price, trend, fib, fvgs, obs, liquidity,
            recent_swing_highs, recent_swing_lows, sweeps, regime, htf_trend,
        )
        sell_confidence, sell_reasons = self._evaluate_sell(
            current_price, trend, fib, fvgs, obs, liquidity,
            recent_swing_highs, recent_swing_lows, sweeps, regime, htf_trend,
        )

        base_meta = {"trend": trend, "regime": regime, "htf_trend": htf_trend}

        if buy_confidence >= self.min_confidence and buy_confidence > sell_confidence:
            entry = self._find_entry(current_price, fib, "BUY")
            sl = self._find_stop(recent_swing_lows, entry, "BUY")
            if sl < entry:
                tp = self._find_targets(entry, sl, "BUY")
                return SignalResult(
                    symbol=symbol, direction="BUY",
                    entry=entry, stop_loss=sl, take_profit=tp,
                    confidence=buy_confidence,
                    metadata={**base_meta, "reasons": buy_reasons,
                              "fib_ote": FibonacciCalculator.ote_zone(fib)},
                )

        if sell_confidence >= self.min_confidence and sell_confidence > buy_confidence:
            entry = self._find_entry(current_price, fib, "SELL")
            sl = self._find_stop(recent_swing_highs, entry, "SELL")
            if sl > entry:
                tp = self._find_targets(entry, sl, "SELL")
                return SignalResult(
                    symbol=symbol, direction="SELL",
                    entry=entry, stop_loss=sl, take_profit=tp,
                    confidence=sell_confidence,
                    metadata={**base_meta, "reasons": sell_reasons,
                              "fib_ote": FibonacciCalculator.ote_zone(fib)},
                )

        return SignalResult(symbol=symbol, direction="NONE", entry=None, stop_loss=None,
                            take_profit=[], confidence=max(buy_confidence, sell_confidence),
                            metadata=base_meta)

    def _determine_trend(self, bos_events: list[BOSEvent]) -> str:
        if not bos_events:
            return "NEUTRAL"
        recent = [b for b in bos_events if b.index > 0]
        if not recent:
            return "NEUTRAL"
        bullish = sum(1 for b in recent[-5:] if b.direction == "BULLISH")
        bearish = sum(1 for b in recent[-5:] if b.direction == "BEARISH")
        if bullish > bearish:
            return "BULLISH"
        if bearish > bullish:
            return "BEARISH"
        return "NEUTRAL"

    def _evaluate_buy(
        self, price: float, trend: str, fib: dict,
        fvgs: list[FVGZone], obs: list[dict], liq: list[dict],
        highs: list[SwingPoint], lows: list[SwingPoint],
        sweeps: list[dict], regime: dict, htf_trend: str,
    ) -> tuple[int, list[str]]:
        confidence = 50
        reasons: list[str] = []

        if trend == "BULLISH":
            confidence += 15
            reasons.append("Тренд 1h: бычий (BOS вверх)")
        elif trend == "BEARISH":
            confidence -= 15

        if htf_trend == "BULLISH":
            confidence += 12
            reasons.append("Старший ТФ 4h подтверждает: бычий")
        elif htf_trend == "BEARISH":
            confidence -= 20
            reasons.append("Против тренда 4h — штраф")

        if regime.get("regime") == "RANGE":
            confidence -= 5

        if FibonacciCalculator.is_discount(price, fib):
            confidence += 15
            reasons.append("Цена в дисконте (ниже 0.5 Fib)")
        else:
            confidence -= 10

        recent_fvgs = [f for f in fvgs if f.direction == "BEARISH"]
        if recent_fvgs:
            last_fvg = recent_fvgs[-1]
            if last_fvg.bottom <= price <= last_fvg.top:
                confidence += 10
                reasons.append("Цена в зоне имбаланса (FVG)")

        bullish_obs = [ob for ob in obs if ob["type"] == "BULLISH"]
        if bullish_obs:
            last_ob = bullish_obs[-1]
            if last_ob["low"] <= price <= last_ob["high"]:
                confidence += 10
                reasons.append("Ретест бычьего ордер-блока")

        if liq:
            buy_side_liq = [l for l in liq if l["type"] == "BUY_SIDE"]
            if buy_side_liq and price <= buy_side_liq[0]["price"] * 1.002:
                confidence += 5
                reasons.append("Рядом пул ликвидности (equal lows)")

        if any(s["type"] == "BULLISH_SWEEP" for s in sweeps):
            confidence += 12
            reasons.append("Снятие ликвидности снизу (sweep) с возвратом")

        sl_candidate = min(s.price for s in lows) if lows else price * 0.98
        tp_candidate = max(s.price for s in highs) if highs else price * 1.05

        if sl_candidate >= price:
            return 0, reasons

        rr = abs(tp_candidate - price) / abs(price - sl_candidate) if abs(price - sl_candidate) > 0 else 0
        if rr < self.min_rr_ratio:
            confidence -= 20

        return max(0, min(100, confidence)), reasons

    def _evaluate_sell(
        self, price: float, trend: str, fib: dict,
        fvgs: list[FVGZone], obs: list[dict], liq: list[dict],
        highs: list[SwingPoint], lows: list[SwingPoint],
        sweeps: list[dict], regime: dict, htf_trend: str,
    ) -> tuple[int, list[str]]:
        confidence = 50
        reasons: list[str] = []

        if trend == "BEARISH":
            confidence += 15
            reasons.append("Тренд 1h: медвежий (BOS вниз)")
        elif trend == "BULLISH":
            confidence -= 15

        if htf_trend == "BEARISH":
            confidence += 12
            reasons.append("Старший ТФ 4h подтверждает: медвежий")
        elif htf_trend == "BULLISH":
            confidence -= 20
            reasons.append("Против тренда 4h — штраф")

        if regime.get("regime") == "RANGE":
            confidence -= 5

        if FibonacciCalculator.is_premium(price, fib):
            confidence += 15
            reasons.append("Цена в премиуме (выше 0.5 Fib)")
        else:
            confidence -= 10

        recent_fvgs = [f for f in fvgs if f.direction == "BULLISH"]
        if recent_fvgs:
            last_fvg = recent_fvgs[-1]
            if last_fvg.bottom <= price <= last_fvg.top:
                confidence += 10
                reasons.append("Цена в зоне имбаланса (FVG)")

        bearish_obs = [ob for ob in obs if ob["type"] == "BEARISH"]
        if bearish_obs:
            last_ob = bearish_obs[-1]
            if last_ob["low"] <= price <= last_ob["high"]:
                confidence += 10
                reasons.append("Ретест медвежьего ордер-блока")

        if liq:
            sell_side_liq = [l for l in liq if l["type"] == "SELL_SIDE"]
            if sell_side_liq and price >= sell_side_liq[0]["price"] * 0.998:
                confidence += 5
                reasons.append("Рядом пул ликвидности (equal highs)")

        if any(s["type"] == "BEARISH_SWEEP" for s in sweeps):
            confidence += 12
            reasons.append("Снятие ликвидности сверху (sweep) с возвратом")

        sl_candidate = max(s.price for s in highs) if highs else price * 1.02
        tp_candidate = min(s.price for s in lows) if lows else price * 0.95

        if sl_candidate <= price:
            return 0, reasons

        rr = abs(price - tp_candidate) / abs(sl_candidate - price) if abs(sl_candidate - price) > 0 else 0
        if rr < self.min_rr_ratio:
            confidence -= 20

        return max(0, min(100, confidence)), reasons

    OTE_MID = 0.702  # midpoint of the 0.618–0.786 OTE retracement zone

    def _find_entry(self, price: float, fib: dict, direction: str) -> float:
        high = fib.get(0.0)
        low = fib.get(1.0)
        if not high or not low or high <= low:
            return round(price, 4)
        diff = high - low
        if direction == "BUY":
            # discount: retracement of the up-leg into the OTE zone
            return round(high - diff * self.OTE_MID, 4)
        # premium: mirror of the OTE zone for shorts
        return round(low + diff * self.OTE_MID, 4)

    def _find_stop(self, swing_points: list, entry: float, direction: str) -> float:
        if direction == "BUY":
            prices = [s.price for s in swing_points] if swing_points else [entry * 0.97]
            return round(min(prices) * 0.998, 4)
        else:
            prices = [s.price for s in swing_points] if swing_points else [entry * 1.03]
            return round(max(prices) * 1.002, 4)

    def _find_targets(self, entry: float, stop: float, direction: str) -> list[float]:
        risk = abs(entry - stop) or entry * 0.01
        sign = 1 if direction == "BUY" else -1
        return [
            round(entry + sign * risk * 3, 4),
            round(entry + sign * risk * 5, 4),
            round(entry + sign * risk * 7, 4),
        ]


class SMCStrategy(AbstractStrategy):
    name = "SMC"
    timeframe = "1h"  # must match the collector's TIMEFRAME

    def __init__(self, min_rr_ratio: float = 3.0, min_confidence: int = 50):
        self.generator = SignalGenerator(min_rr_ratio=min_rr_ratio, min_confidence=min_confidence)

    def generate_signal(self, df: pd.DataFrame, symbol: str = "",
                        htf_df: pd.DataFrame | None = None) -> SignalResult:
        if len(df) < 50:
            return SignalResult(symbol=symbol, direction="NONE", entry=None, stop_loss=None,
                                take_profit=[], confidence=0, metadata={"error": "Insufficient data"})

        swings = StructuralAnalysis.detect_swing_points(df)
        bos_events = StructuralAnalysis.detect_bos(df, swings)
        fvgs = StructuralAnalysis.detect_fvg(df)
        obs = StructuralAnalysis.detect_order_blocks(df)
        liquidity = StructuralAnalysis.detect_liquidity_levels(swings)
        sweeps = StructuralAnalysis.detect_liquidity_sweeps(df, liquidity)
        regime = StructuralAnalysis.detect_regime(df)
        htf_trend = self._htf_trend(htf_df)

        signal = self.generator.generate(
            df, swings, bos_events, fvgs, obs, liquidity, symbol,
            sweeps=sweeps, regime=regime, htf_trend=htf_trend,
        )

        logger.info(
            "SMC signal: %s %s entry=%s sl=%s tp=%s conf=%d",
            signal.symbol, signal.direction, signal.entry,
            signal.stop_loss, signal.take_profit, signal.confidence,
        )

        return signal

    def _htf_trend(self, htf_df: pd.DataFrame | None) -> str:
        """Higher-timeframe bias from the same BOS logic, run on 4h candles."""
        if htf_df is None or len(htf_df) < 50:
            return "NEUTRAL"
        htf_swings = StructuralAnalysis.detect_swing_points(htf_df)
        htf_bos = StructuralAnalysis.detect_bos(htf_df, htf_swings)
        return self.generator._determine_trend(htf_bos)

    def backtest(self, df: pd.DataFrame, symbol: str = "") -> BacktestResult:
        return super().backtest(df, symbol)
