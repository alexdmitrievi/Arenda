import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.trade import Position, Signal, Trade, TradeSide, TradeStatus
from app.services.trading.exchange import (
    create_limit_order,
    create_market_order,
    create_stop_loss_order,
    create_take_profit_order,
)
from app.services.trading.risk import RiskManager, calculate_position_size

logger = logging.getLogger("tbx.trading.engine")


async def execute_signal(
    user_id: UUID,
    exchange: Any,
    signal: Signal,
    balance: float,
    risk_pct: float = 2.0,
) -> Trade | None:
    if signal.executed:
        logger.warning("Signal %s already executed", signal.id)
        return None

    risk_amount, pos_size_quote, pos_size_base = calculate_position_size(
        balance=balance,
        risk_pct=risk_pct,
        entry_price=float(signal.entry),
        stop_loss_price=float(signal.stop_loss),
    )

    logger.info(
        "Executing signal %s: %s %s entry=%.4f sl=%.4f size=%.6f risk=$%.2f",
        signal.id, signal.symbol, signal.direction.value,
        signal.entry, signal.stop_loss, pos_size_base, risk_amount,
    )

    try:
        order = await create_limit_order(
            exchange=exchange,
            symbol=signal.symbol,
            side="buy" if signal.direction == TradeSide.BUY else "sell",
            amount=pos_size_base,
            price=float(signal.entry),
        )

        trade = Trade(
            user_id=str(user_id),
            exchange=exchange.id,
            symbol=signal.symbol,
            side=signal.direction,
            strategy_id=str(signal.strategy_id),
            signal_id=str(signal.id),
            entry_price=signal.entry,
            size=Decimal(str(pos_size_base)),
            status=TradeStatus.OPEN,
        )
        signal.executed = True

        async with async_session_factory() as db:
            db.add(trade)
            db.add(signal)
            await db.commit()

        logger.info("Order placed: %s", order.get("id"))
        return trade

    except Exception as e:
        logger.error("Failed to execute signal %s: %s", signal.id, e)
        return None


async def close_trade(
    trade: Trade,
    exchange: ccxt_async.Exchange,
    exit_price: float,
) -> Trade:
    try:
        await create_market_order(
            exchange=exchange,
            symbol=trade.symbol,
            side="sell" if trade.side == TradeSide.BUY else "buy",
            amount=float(trade.size),
        )

        entry = float(trade.entry_price)
        size = float(trade.size)
        pnl = (exit_price - entry) * size
        if trade.side == TradeSide.SELL:
            pnl = -pnl
        pnl_pct = ((exit_price - entry) / entry * 100)
        if trade.side == TradeSide.SELL:
            pnl_pct = -pnl_pct

        trade.exit_price = Decimal(str(round(exit_price, 4)))
        trade.pnl = Decimal(str(round(pnl, 2)))
        trade.pnl_pct = Decimal(str(round(pnl_pct, 2)))
        trade.status = TradeStatus.CLOSED
        trade.closed_at = datetime.now(timezone.utc)

        logger.info("Trade %s closed: PnL $%.2f (%.2f%%)", trade.id, pnl, pnl_pct)

    except Exception as e:
        logger.error("Failed to close trade %s: %s", trade.id, e)

    return trade


async def place_oco_stops(
    exchange: ccxt_async.Exchange,
    trade: Trade,
    stop_loss_price: float,
    take_profit_price: float,
) -> tuple[dict | None, dict | None]:
    close_side = "sell" if trade.side == TradeSide.BUY else "buy"
    amount = float(trade.size)

    sl_order = tp_order = None

    try:
        sl_order = await create_stop_loss_order(
            exchange=exchange,
            symbol=trade.symbol,
            side=close_side,
            amount=amount,
            stop_price=stop_loss_price,
        )
    except Exception as e:
        logger.error("Failed to place SL for trade %s: %s", trade.id, e)

    try:
        tp_order = await create_take_profit_order(
            exchange=exchange,
            symbol=trade.symbol,
            side=close_side,
            amount=amount,
            tp_price=take_profit_price,
        )
    except Exception as e:
        logger.error("Failed to place TP for trade %s: %s", trade.id, e)

    return sl_order, tp_order


async def emergency_close_all(
    exchange: ccxt_async.Exchange,
    symbol: str | None = None,
) -> int:
    count = 0
    try:
        positions = await exchange.fetch_positions()
        for pos in positions:
            if pos.get("contracts", 0) <= 0:
                continue
            pos_symbol = pos.get("symbol", "")
            if symbol and pos_symbol != symbol:
                continue
            close_side = "sell" if pos.get("side", "long") == "long" else "buy"
            await create_market_order(
                exchange=exchange,
                symbol=pos_symbol,
                side=close_side,
                amount=abs(float(pos.get("contracts", 0))),
                params={"reduceOnly": True},
            )
            count += 1
            logger.warning("Kill-switch: closed position %s", pos_symbol)
    except Exception as e:
        logger.error("Kill-switch failed: %s", e)
    return count
