"""Background maintenance loops (asyncio tasks, started from the app lifespan).

Replaces the never-deployed Celery workers: at this scale two plain loops
cover everything that must happen off the request path.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.trade import Trade, TradeStatus
from app.models.user import User

logger = logging.getLogger("tbx.scheduler")

SUBSCRIPTION_INTERVAL = 3600
RECONCILE_INTERVAL = 300
PENDING_TRADE_TIMEOUT = timedelta(minutes=10)
REMINDER_WINDOW = timedelta(days=3)


async def subscription_maintenance_loop():
    while True:
        try:
            await _expire_subscriptions()
            await _send_expiry_reminders()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Subscription maintenance failed: %s", e)
        await asyncio.sleep(SUBSCRIPTION_INTERVAL)


async def _expire_subscriptions():
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        result = await db.execute(
            update(Subscription)
            .where(
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
                Subscription.expires_at.is_not(None),
                Subscription.expires_at < now,
            )
            .values(status=SubscriptionStatus.EXPIRED)
            .returning(Subscription.id)
        )
        expired = result.scalars().all()
        await db.commit()
    if expired:
        logger.info("Marked %d subscriptions as expired", len(expired))


async def _send_expiry_reminders():
    from app.bot.bot import send_message_safe

    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        rows = await db.execute(
            select(Subscription, User.telegram_id)
            .join(User, User.id == Subscription.user_id)
            .where(
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
                Subscription.expires_at.is_not(None),
                Subscription.expires_at > now,
                Subscription.expires_at < now + REMINDER_WINDOW,
                User.telegram_id.is_not(None),
            )
        )
        pairs = rows.all()

    if not pairs:
        return

    redis = await get_redis()
    for sub, telegram_id in pairs:
        # one reminder per subscription per expiry window
        dedup_key = f"remind:sub:{sub.id}"
        if not await redis.set(dedup_key, "1", ex=4 * 86400, nx=True):
            continue
        days_left = max(1, (sub.expires_at - now).days)
        await send_message_safe(
            telegram_id,
            f"⏳ Подписка TBX ({sub.plan.value}) истекает через {days_left} дн. "
            "Продлите её, чтобы не потерять real-time сигналы.",
        )


async def trade_reconciliation_loop():
    """Trades stuck in PENDING mean the exchange order step never confirmed.

    They are flagged loudly for review instead of silently living forever:
    the position may or may not exist on the exchange, and only the user's
    API keys can answer that, so an operator has to look.
    """
    while True:
        try:
            await _flag_stale_pending_trades()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Trade reconciliation failed: %s", e)
        await asyncio.sleep(RECONCILE_INTERVAL)


async def _flag_stale_pending_trades():
    cutoff = datetime.now(timezone.utc) - PENDING_TRADE_TIMEOUT
    async with async_session_factory() as db:
        result = await db.execute(
            select(Trade).where(
                Trade.status == TradeStatus.PENDING,
                Trade.created_at < cutoff,
            )
        )
        stale = result.scalars().all()
        for trade in stale:
            trade.status = TradeStatus.CANCELLED
            logger.error(
                "RECONCILE: trade %s (%s %s user=%s) stuck in PENDING > %s — "
                "marked CANCELLED. Verify on the exchange whether the order exists!",
                trade.id, trade.symbol, trade.side, trade.user_id, PENDING_TRADE_TIMEOUT,
            )
        await db.commit()


def start_scheduler() -> list[asyncio.Task]:
    return [
        asyncio.create_task(subscription_maintenance_loop()),
        asyncio.create_task(trade_reconciliation_loop()),
    ]
