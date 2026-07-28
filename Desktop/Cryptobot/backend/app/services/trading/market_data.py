import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from app.core.redis import get_redis

logger = logging.getLogger("tbx.market_data")


async def publish_ticker(redis: aioredis.Redis, symbol: str, ticker: dict):
    channel = f"ticker:{symbol}"
    await redis.publish(channel, json.dumps({
        "symbol": symbol,
        "price": ticker.get("last"),
        "bid": ticker.get("bid"),
        "ask": ticker.get("ask"),
        "volume": ticker.get("baseVolume"),
        "change_24h": ticker.get("percentage"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))


async def publish_ohlcv(redis: aioredis.Redis, symbol: str, timeframe: str, candle: list):
    channel = f"ohlcv:{symbol}:{timeframe}"
    await redis.publish(channel, json.dumps({
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": candle[0],
        "open": candle[1],
        "high": candle[2],
        "low": candle[3],
        "close": candle[4],
        "volume": candle[5],
    }))


async def cache_ohlcv(redis: aioredis.Redis, symbol: str, timeframe: str, candles: list[list]):
    key = f"candles:{symbol}:{timeframe}"
    await redis.set(key, json.dumps(candles), ex=3600)


async def get_cached_ohlcv(redis: aioredis.Redis, symbol: str, timeframe: str) -> list[list] | None:
    key = f"candles:{symbol}:{timeframe}"
    data = await redis.get(key)
    if data:
        return json.loads(data)
    return None


async def get_latest_price(redis: aioredis.Redis, symbol: str) -> float | None:
    key = f"price:{symbol}"
    data = await redis.get(key)
    if data:
        return float(data)
    return None


async def set_latest_price(redis: aioredis.Redis, symbol: str, price: float):
    key = f"price:{symbol}"
    await redis.set(key, str(price), ex=60)


async def get_market_snapshot(redis: aioredis.Redis, symbols: list[str]) -> dict[str, float | None]:
    keys = [f"price:{s}" for s in symbols]
    prices = await redis.mget(keys)
    return {s: float(p) if p else None for s, p in zip(symbols, prices)}
