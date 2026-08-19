"""Smart DCA engine for investors.

Rule-based, like everything else in TBX: a fixed weekly budget whose
per-asset spend is scaled by how cheap the asset is relative to its own
history. Buy more into weakness, less into euphoria — never sell, never
use leverage, never touch anything illiquid.

Multiplier logic per asset (bounded 0.25x–3.0x):
  price below 200d MA          +0.5   (accumulation zone)
  >20% below 200d MA           +0.5   (deep discount)
  drawdown from 1y high >30%   +0.5
  drawdown from 1y high >50%   +0.5
  price >50% above 200d MA     -0.75  (euphoria — trim the buys)

Allocation starts BTC-heavy and tilts toward alts only when the
altseason score confirms breadth (>=75), or back to BTC when <=25.
"""

import logging
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger("tbx.strategies.dca_smart")

DCA_ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
BASE_WEIGHTS = {"BTC/USDT": 0.45, "ETH/USDT": 0.30, "SOL/USDT": 0.15, "BNB/USDT": 0.10}
ALTSEASON_TILT = 0.10  # share shifted between BTC and alts at the extremes

MIN_MULTIPLIER = 0.25
MAX_MULTIPLIER = 3.0


@dataclass
class DCAAssetPlan:
    symbol: str
    weight: float
    multiplier: float
    amount_usd: float
    price: float
    reasons: list[str] = field(default_factory=list)


def asset_multiplier(daily_closes: pd.Series) -> tuple[float, list[str]]:
    """Spend multiplier from the asset's own valuation history."""
    multiplier = 1.0
    reasons: list[str] = []

    if len(daily_closes) < 60:
        return multiplier, ["Мало истории — базовая ставка"]

    price = float(daily_closes.iloc[-1])
    ma200 = float(daily_closes.rolling(min(200, len(daily_closes))).mean().iloc[-1])
    year_high = float(daily_closes.tail(365).max())
    drawdown = 1 - price / year_high if year_high > 0 else 0.0

    if ma200 > 0:
        deviation = price / ma200 - 1
        if deviation < 0:
            multiplier += 0.5
            reasons.append("Цена ниже 200-дневной средней — зона накопления")
            if deviation < -0.20:
                multiplier += 0.5
                reasons.append("Глубокий дисконт: >20% ниже MA200")
        elif deviation > 0.50:
            multiplier -= 0.75
            reasons.append("Перегрев: >50% выше MA200 — покупки урезаны")

    if drawdown > 0.30:
        multiplier += 0.5
        reasons.append(f"Просадка от годового максимума {drawdown:.0%}")
    if drawdown > 0.50:
        multiplier += 0.5
        reasons.append("Экстремальная просадка >50% — усиленный набор")

    multiplier = max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, multiplier))
    if not reasons:
        reasons.append("Нейтральная зона — базовая ставка")
    return round(multiplier, 2), reasons


def allocation_weights(altseason_score: float | None) -> dict[str, float]:
    weights = dict(BASE_WEIGHTS)
    if altseason_score is None:
        return weights
    if altseason_score >= 75:
        # confirmed altseason: shift part of the BTC share to alts
        weights["BTC/USDT"] -= ALTSEASON_TILT
        alt_symbols = [s for s in weights if s != "BTC/USDT"]
        for s in alt_symbols:
            weights[s] += ALTSEASON_TILT / len(alt_symbols)
    elif altseason_score <= 25:
        # BTC season: pull risk back into BTC
        alt_symbols = [s for s in weights if s != "BTC/USDT"]
        for s in alt_symbols:
            weights[s] -= ALTSEASON_TILT / len(alt_symbols)
        weights["BTC/USDT"] += ALTSEASON_TILT

    # renormalise: rounding the tilted shares must not drift the budget
    rounded = {s: round(w, 4) for s, w in weights.items()}
    total = sum(rounded.values())
    if total > 0 and abs(total - 1.0) > 1e-9:
        largest = max(rounded, key=rounded.get)
        rounded[largest] = round(rounded[largest] + (1.0 - total), 4)
    return rounded


def build_plan(
    budget_usd: float,
    daily_closes_by_symbol: dict[str, pd.Series],
    altseason_score: float | None = None,
) -> list[DCAAssetPlan]:
    weights = allocation_weights(altseason_score)
    plan = []
    for symbol in DCA_ASSETS:
        closes = daily_closes_by_symbol.get(symbol)
        if closes is None or closes.empty:
            continue
        multiplier, reasons = asset_multiplier(closes)
        weight = weights.get(symbol, 0.0)
        amount = round(budget_usd * weight * multiplier, 2)
        plan.append(DCAAssetPlan(
            symbol=symbol,
            weight=weight,
            multiplier=multiplier,
            amount_usd=amount,
            price=float(closes.iloc[-1]),
            reasons=reasons,
        ))
    return plan
