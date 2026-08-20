"""Database <-> exchange reconciliation for open trades.

When a stop-loss or take-profit fires on the exchange, nothing informs the
application: the protective orders are exchange-side. This module detects the
closing fill in the user's execution history and records the close in the DB
with the real price and fee, so the database stops diverging from reality.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.models.trade import Trade, TradeSide, TradeStatus

logger = logging.getLogger("tbx.trading.sync")

_CLOSE_MATCH_EPS = 0.999  # sell fills summing to >= 99.9% of the size count as a close


def match_close_fills(fills: list[dict], trade_side: str, size: float) -> tuple[list[dict], float, float]:
    """Pick the fills that close a trade of the given side and size.

    Returns (matched_fills, volume_weighted_price, total_fee_cost).
    """
    close_side = "sell" if trade_side in ("buy", TradeSide.BUY) else "buy"
    matched: list[dict] = []
    total_amount = 0.0
    total_notional = 0.0
    total_fee = 0.0
    for fill in fills:
        if str(fill.get("side", "")).lower() != close_side:
            continue
        amount = float(fill.get("amount") or 0)
        if amount <= 0:
            continue
        price = float(fill.get("price") or 0)
        fee_cost = 0.0
        fee = fill.get("fee") or {}
        if fee.get("cost") is not None:
            fee_cost = float(fee["cost"])
        matched.append(fill)
        total_amount += amount
        total_notional += price * amount
        total_fee += fee_cost
        if total_amount >= size * _CLOSE_MATCH_EPS:
            break
    if total_amount < size * _CLOSE_MATCH_EPS:
        return [], 0.0, 0.0
    avg_price = total_notional / total_amount if total_amount > 0 else 0.0
    return matched, avg_price, total_fee


def record_trade_close(trade: Trade, exit_price: float, fee_cost: float | None = None) -> None:
    """Mark a trade CLOSED and store pnl/fee — shared by manual close and sync."""
    trade.status = TradeStatus.CLOSED
    trade.closed_at = datetime.now(timezone.utc)
    trade.exit_price = Decimal(str(exit_price))

    entry = float(trade.entry_price)
    size = float(trade.size)
    direction = 1 if str(trade.side) == "buy" or trade.side == TradeSide.BUY else -1
    pnl = (exit_price - entry) * size * direction
    if fee_cost:
        pnl -= fee_cost
        trade.fee = (trade.fee or Decimal("0")) + Decimal(str(fee_cost))
    trade.pnl = Decimal(str(round(pnl, 2)))
    notional = entry * size
    if notional > 0:
        trade.pnl_pct = Decimal(str(round(pnl / notional * 100, 2)))


async def sync_trades_for_user(exchange, trades: list[Trade]) -> list[Trade]:
    """Fetch the user's fills and close any trade whose protective order fired.

    Returns the trades that were closed (already mutated).
    """
    closed: list[Trade] = []
    for trade in trades:
        try:
            since_ms = int(trade.created_at.timestamp() * 1000) - 60_000 if trade.created_at else None
            fills = await exchange.fetch_my_trades(
                trade.symbol, since=since_ms, limit=200
            )
            _, exit_price, fee_cost = match_close_fills(fills, str(trade.side), float(trade.size))
            if exit_price > 0:
                record_trade_close(trade, exit_price, fee_cost)
                closed.append(trade)
                logger.info(
                    "Synced exchange close: trade %s %s exit=%.4f pnl=%s",
                    trade.id, trade.symbol, exit_price, trade.pnl,
                )
        except Exception as e:
            logger.error("Sync failed for trade %s %s: %s", trade.id, trade.symbol, e)
    return closed
