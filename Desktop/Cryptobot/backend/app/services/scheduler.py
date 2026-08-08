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
MARKET_CONTEXT_INTERVAL = 1800
PENDING_TRADE_TIMEOUT = timedelta(minutes=10)
REMINDER_WINDOW = timedelta(days=3)


async def market_context_loop():
    """Refreshes the market-context snapshot (BTC bias, altseason, macro) in Redis."""
    import ccxt.async_support as ccxt_async

    from app.config import settings
    from app.services.market_context.engine import compute_context, store_context

    while True:
        exchange = ccxt_async.binance({"enableRateLimit": True})
        try:
            context = await compute_context(
                exchange, getattr(settings, "MACRO_EVENTS_JSON", "")
            )
            await store_context(context)
            logger.info(
                "Market context: btc=%s altseason=%s blackout=%s",
                context["btc"]["mode"], context["altseason"]["score"],
                context["macro_blackout"]["active"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Market context refresh failed: %s", e)
        finally:
            try:
                await exchange.close()
            except Exception:
                pass
        await asyncio.sleep(MARKET_CONTEXT_INTERVAL)


async def subscription_maintenance_loop():
    while True:
        try:
            await _expire_subscriptions()
            await _send_expiry_reminders()
            await _send_weekly_dca_reminder()
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


async def _send_weekly_dca_reminder():
    """Monday nudge for investors: the weekly DCA window is open."""
    from app.bot.bot import send_message_safe

    now = datetime.now(timezone.utc)
    if now.weekday() != 0 or now.hour < 12:
        return

    redis = await get_redis()
    if not await redis.set(f"remind:dca:{now.isocalendar().week}", "1", ex=6 * 86400, nx=True):
        return

    from sqlalchemy import or_

    async with async_session_factory() as db:
        active_ids = select(Subscription.user_id).where(
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
        )
        rows = await db.execute(
            select(User.telegram_id).where(
                User.telegram_id.is_not(None),
                User.is_active.is_(True),
                or_(User.referred_by.is_not(None), User.id.in_(active_ids)),
            )
        )
        telegram_ids = list(rows.scalars().all())

    for telegram_id in telegram_ids:
        await send_message_safe(
            telegram_id,
            "📅 Еженедельное DCA-окно открыто. Загляните в раздел «Инвестор» — "
            "план покупок уже рассчитан с учётом просадок и фазы рынка.",
        )
        await asyncio.sleep(0.05)
    if telegram_ids:
        logger.info("Weekly DCA reminder sent to %d users", len(telegram_ids))


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
        asyncio.create_task(market_context_loop()),
    ]
