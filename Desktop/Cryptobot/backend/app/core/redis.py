import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.config import settings

redis_client: Redis | None = None


async def init_redis() -> Redis:
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return redis_client


async def close_redis() -> None:
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


async def get_redis() -> Redis:
    if redis_client is None:
        return await init_redis()
    return redis_client
