"""Pushes freshly generated signals to Telegram subscribers.

Listens on the same Redis channel the collector publishes to, so signal
generation and delivery stay decoupled.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User

logger = logging.getLogger("tbx.notifications.broadcaster")

SIGNALS_CHANNEL = "signals:new"
# stay well under Telegram's ~30 msg/sec bulk limit
SEND_PAUSE_SECONDS = 0.05


def format_signal_message(payload: dict) -> str:
    direction = str(payload.get("direction", "")).upper()
    icon = "🟢" if direction == "BUY" else "🔴"
    tps = payload.get("take_profit") or []
    tp_line = " / ".join(f"{tp:g}" for tp in tps) if tps else "—"
    return (
        f"{icon} Сигнал: {payload.get('symbol')} — {direction} "
        f"(уверенность {payload.get('confidence')}%)\n"
        f"Вход: {payload.get('entry'):g}\n"
        f"Стоп: {payload.get('stop_loss'):g}\n"
        f"Цели: {tp_line}"
    )


async def _eligible_telegram_ids() -> list[int]:
    now = datetime.now(timezone.utc)
    active_user_ids = select(Subscription.user_id).where(
        Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
        or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
    )
    async with async_session_factory() as db:
        result = await db.execute(
            select(User.telegram_id).where(
                User.telegram_id.is_not(None),
                User.is_active.is_(True),
                or_(User.referred_by.is_not(None), User.id.in_(active_user_ids)),
            )
        )
        return list(result.scalars().all())


async def _broadcast_signal(payload: dict):
    from app.bot.bot import send_message_safe

    telegram_ids = await _eligible_telegram_ids()
    if not telegram_ids:
        return

    text = format_signal_message(payload)
    sent = 0
    for telegram_id in telegram_ids:
        if await send_message_safe(telegram_id, text):
            sent += 1
        await asyncio.sleep(SEND_PAUSE_SECONDS)
    logger.info("Signal %s broadcast to %d/%d users", payload.get("id"), sent, len(telegram_ids))


async def _listen():
    redis = await get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(SIGNALS_CHANNEL)
    logger.info("Signal broadcaster subscribed to %s", SIGNALS_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
                await _broadcast_signal(payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Failed to broadcast signal: %s", e)
    finally:
        await pubsub.unsubscribe(SIGNALS_CHANNEL)
        await pubsub.close()


async def broadcast_loop():
    while True:
        try:
            await _listen()
        except asyncio.CancelledError:
            logger.info("Signal broadcaster cancelled")
            raise
        except Exception as e:
            logger.error("Broadcaster error, restarting in 5s: %s", e)
            await asyncio.sleep(5)


def start_broadcaster() -> asyncio.Task:
    return asyncio.create_task(broadcast_loop())
