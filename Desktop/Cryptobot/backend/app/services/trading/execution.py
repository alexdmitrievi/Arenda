"""Execution hardening: size math, RR enforcement and stop verification.

Invariant: a position must never exist without a stop-loss. The entry order
carries the stop attached at creation, but we also verify AFTER the fill that
a stop actually exists on the exchange, and place one if the exchange silently
dropped the parameter. If the stop cannot be attached at all, the caller must
close the position immediately.
"""

import logging

from app.services.trading.exchange import (
    create_stop_loss_order,
    create_take_profit_order,
)

logger = logging.getLogger("tbx.trading.execution")

MIN_RR_RATIO = 2.0  # product mandate: reward-to-risk at least 1:2 (owner decision 2026-08-20)
DEFAULT_RISK_PCT = 2.0  # product mandate: 2% of deposit risked per trade

_PRICE_EPS = 1e-6


def stop_zone_and_rr(entry: float, stop: float, tp: float | None) -> tuple[float, float | None]:
    """Stop-loss width in % of entry and reward-to-risk to the first target."""
    stop_distance = abs(entry - stop)
    if stop_distance <= 0 or entry <= 0:
        return 0.0, None
    zone = round(stop_distance / entry * 100, 2)
    rr = round(abs(tp - entry) / stop_distance, 2) if tp is not None else None
    return zone, rr


class StopLossFailure(Exception):
    """Raised when a protective stop could not be attached to an open position."""


def compute_position_size(balance: float, risk_pct: float, entry: float, stop: float) -> float:
    """Base-amount for a position that risks risk_pct% of the balance on the stop distance.

    Equivalent to the owner's risk-calculator formula expressed in percentages:
        stop_zone_pct = |entry - stop| / entry * 100
        position_volume_usd = balance * risk_pct / stop_zone_pct
        size_base = position_volume_usd / entry
    Leverage never enters the formula — it only affects the margin required.
    """
    if balance <= 0:
        raise ValueError("Balance must be positive")
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        raise ValueError("Invalid stop-loss distance")
    risk_amount = balance * (risk_pct / 100.0)
    return round(risk_amount / stop_distance, 6)


def position_metrics(
    entry: float,
    stop: float,
    tp: float | None,
    balance: float,
    risk_pct: float,
    leverage: float | None = None,
) -> dict:
    """Full risk block, mirroring the owner's futures risk calculator.

    Example: $1000 deposit, 2% risk, 7% stop zone → volume $285.71.
    """
    stop_distance = abs(entry - stop)
    if stop_distance <= 0 or entry <= 0:
        raise ValueError("Invalid stop-loss geometry")
    stop_zone_pct = round(stop_distance / entry * 100, 2)
    risk_amount = round(balance * (risk_pct / 100.0), 2)
    volume_usd = round(risk_amount / (stop_zone_pct / 100.0), 2)
    size_base = round(volume_usd / entry, 6)
    rr = None
    if tp is not None:
        rr = round(abs(tp - entry) / stop_distance, 2)
    margin_required = None
    if leverage and leverage > 0:
        margin_required = round(volume_usd / leverage, 2)
    return {
        "entry": round(entry, 8),
        "stop_loss": round(stop, 8),
        "take_profit": tp,
        "deposit": round(balance, 2),
        "risk_pct": risk_pct,
        "risk_amount": risk_amount,
        "stop_zone_pct": stop_zone_pct,
        "position_volume_usd": volume_usd,
        "position_size_base": size_base,
        "rr": rr,
        "leverage": leverage,
        "margin_required": margin_required,
    }


def validate_geometry(entry: float, stop: float, tp: float | None, min_rr: float = MIN_RR_RATIO) -> None:
    """Raise ValueError unless the trade carries at least min_rr reward-to-risk."""
    if tp is None:
        raise ValueError("Take-profit is required: the 3:1 reward-to-risk mandate cannot be checked")
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        raise ValueError("Invalid stop-loss distance")
    reward = abs(tp - entry)
    rr = reward / stop_distance
    if rr < min_rr:
        raise ValueError(
            f"Reward-to-risk {rr:.2f} is below the required {min_rr}:1"
        )


def _orders_close_to(orders: list[dict], price: float) -> list[dict]:
    matched = []
    for order in orders:
        trigger = None
        info = order.get("info") or {}
        if order.get("triggerPrice") is not None:
            trigger = float(order["triggerPrice"])
        elif info.get("triggerPrice") is not None:
            trigger = float(info["triggerPrice"])
        if trigger is not None and abs(trigger - price) / max(abs(price), 1e-9) < 0.01:
            matched.append(order)
    return matched


async def ensure_stop_attached(
    exchange,
    symbol: str,
    side: str,
    amount: float,
    stop_price: float,
    tp_price: float | None,
) -> dict[str, str | None]:
    """Verify protective orders exist for an open position; place what is missing.

    Returns {"stop_order_id": ..., "tp_order_id": ...}. Raises StopLossFailure
    when the stop cannot be placed — the caller must close the position.
    """
    close_side = "sell" if side == "buy" else "buy"

    try:
        open_orders = await exchange.fetch_open_orders(symbol)
    except Exception:
        open_orders = []

    stop_matches = _orders_close_to(open_orders, stop_price)
    stop_order_id = str(stop_matches[0].get("id")) if stop_matches else None

    if stop_order_id is None:
        try:
            stop_order = await create_stop_loss_order(
                exchange, symbol, close_side, amount, stop_price
            )
            stop_order_id = str(stop_order.get("id")) or None
        except Exception as e:
            logger.error("Failed to attach stop-loss for %s: %s", symbol, e)
            raise StopLossFailure(f"Stop-loss placement failed: {str(e)[:200]}") from e
        if not stop_order_id:
            raise StopLossFailure("Stop-loss placement returned no order id")

    tp_order_id = None
    if tp_price:
        tp_matches = _orders_close_to(open_orders, tp_price)
        if tp_matches:
            tp_order_id = str(tp_matches[0].get("id"))
        else:
            try:
                tp_order = await create_take_profit_order(
                    exchange, symbol, close_side, amount, tp_price
                )
                tp_order_id = str(tp_order.get("id")) or None
            except Exception as e:
                # missing TP is survivable as long as the stop exists
                logger.error("Failed to attach take-profit for %s: %s", symbol, e)

    return {"stop_order_id": stop_order_id, "tp_order_id": tp_order_id}
