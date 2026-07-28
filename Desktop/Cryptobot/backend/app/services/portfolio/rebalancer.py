import logging
from decimal import Decimal

logger = logging.getLogger("tbx.portfolio.rebalancer")


def should_rebalance(
    target_allocation: dict[str, float],
    current_allocation: dict[str, float],
    threshold_pct: float = 5.0,
) -> tuple[bool, dict[str, float]]:
    adjustments = {}
    needs_rebalance = False

    for asset, target_pct in target_allocation.items():
        current_pct = current_allocation.get(asset, 0)
        deviation = abs(current_pct - target_pct)
        if deviation > threshold_pct:
            needs_rebalance = True
            adjustments[asset] = round(target_pct - current_pct, 2)

    return needs_rebalance, adjustments


def calculate_rebalance_trades(
    adjustments: dict[str, float],
    total_value: float,
    current_prices: dict[str, float],
) -> list[dict]:
    trades = []

    for asset, adj_pct in adjustments.items():
        if abs(adj_pct) < 0.1:
            continue

        value = total_value * abs(adj_pct) / 100
        price = current_prices.get(asset, 0)
        quantity = value / price if price > 0 else 0

        trades.append({
            "asset": asset,
            "side": "buy" if adj_pct > 0 else "sell",
            "value_usd": round(value, 2),
            "quantity": round(quantity, 6),
            "adjustment_pct": round(adj_pct, 2),
        })

    return trades
