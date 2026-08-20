"""Global trading kill switch.

`trading:halt` in Redis stops new signals and new executions. Fails closed:
if Redis is unreachable the switch reports halted — an outage must not
silently resume trading while an operator believes it is stopped.
"""

import json
import logging
from datetime import datetime, timezone

from app.core.redis import get_redis

logger = logging.getLogger("tbx.trading.killswitch")

HALT_KEY = "trading:halt"


async def is_trading_halted() -> bool:
    try:
        redis = await get_redis()
        return bool(await redis.get(HALT_KEY))
    except Exception as e:
        logger.error("Kill switch: Redis unavailable, treating trading as halted: %s", e)
        return True


async def set_trading_halt(reason: str) -> dict:
    redis = await get_redis()
    payload = {"reason": reason, "at": datetime.now(timezone.utc).isoformat()}
    await redis.set(HALT_KEY, json.dumps(payload))
    logger.warning("KILL SWITCH: trading halted — %s", reason)
    return payload


async def clear_trading_halt() -> None:
    redis = await get_redis()
    await redis.delete(HALT_KEY)
    logger.warning("KILL SWITCH: trading resumed")


async def get_trading_halt_info() -> dict | None:
    redis = await get_redis()
    raw = await redis.get(HALT_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"reason": str(raw), "at": None}


async def close_all_positions(exchange) -> list[dict]:
    """Close every open USDT-M perpetual position with reduceOnly market orders."""
    closed = []
    positions = await exchange.fetch_positions()
    for pos in positions:
        contracts = float(pos.get("contracts") or 0)
        if contracts == 0:
            continue
        symbol = pos.get("symbol", "")
        close_side = "sell" if str(pos.get("side", "long")) == "long" else "buy"
        amount = abs(contracts)
        try:
            amount = float(exchange.amount_to_precision(symbol, amount))
            if amount <= 0:
                continue
            order = await exchange.create_order(
                symbol, "market", close_side, amount,
                None, {"reduceOnly": True},
            )
            closed.append({
                "symbol": symbol,
                "amount": amount,
                "side": close_side,
                "price": float(order.get("average") or order.get("price") or 0),
                "order_id": str(order.get("id") or ""),
            })
            logger.warning("Kill switch: closed %s %s (%s)", symbol, close_side, amount)
        except Exception as e:
            logger.error("Kill switch: failed to close %s: %s", symbol, e)
            closed.append({"symbol": symbol, "error": str(e)[:200]})
    return closed
