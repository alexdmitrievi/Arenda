"""Background maintenance loops (asyncio tasks, started from the app lifespan).

Replaces the never-deployed Celery workers: at this scale two plain loops
cover everything that must happen off the request path.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.trade import Trade, TradeStatus
from app.models.user import User

logger = logging.getLogger("tbx.scheduler")

SUBSCRIPTION_INTERVAL = 3600
RECONCILE_INTERVAL = 300
POSITION_SYNC_INTERVAL = 60
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
    """Trades stuck in PENDING are resolved against the exchange.

    New trades carry a client_order_id, so the exchange itself can say whether
    the order exists: filled → recover to OPEN, absent → CANCELLED. Only legacy
    rows without a client id are cancelled blind (and logged loudly). Rows that
    cannot be verified because the exchange is unreachable stay PENDING for the
    next pass — a blind cancel could orphan a real position.
    """
    while True:
        try:
            await _resolve_stale_pending_trades()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Trade reconciliation failed: %s", e)
        await asyncio.sleep(RECONCILE_INTERVAL)


async def position_sync_loop():
    """Detect protective orders (SL/TP) filled on the exchange and close the
    matching Trade rows in the DB with real fill prices and fees."""
    while True:
        try:
            await _sync_open_bybit_trades()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Position sync failed: %s", e)
        await asyncio.sleep(POSITION_SYNC_INTERVAL)


async def _sync_open_bybit_trades():
    from app.services.trading.bybit import make_client
    from app.services.trading.credentials import get_bybit_credentials
    from app.services.trading.sync import sync_trades_for_user

    async with async_session_factory() as db:
        result = await db.execute(
            select(Trade).where(
                Trade.exchange == "bybit",
                Trade.status == TradeStatus.OPEN,
            )
        )
        trades = result.scalars().all()
        if not trades:
            return
        user_ids = {t.user_id for t in trades}
        users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        user_map = {u.id: u for u in users}
        by_user: dict = {}
        for trade in trades:
            by_user.setdefault(trade.user_id, []).append(trade)

    closed_trades: list[Trade] = []
    for user_id, user_trades in by_user.items():
        user = user_map.get(user_id)
        credentials = get_bybit_credentials(user) if user else None
        if not credentials:
            continue
        exchange = make_client(credentials[0], credentials[1])
        try:
            await exchange.load_markets()
            closed_trades.extend(await sync_trades_for_user(exchange, user_trades))
        except Exception as e:
            logger.error("Position sync for user %s failed: %s", user_id, e)
        finally:
            try:
                await exchange.close()
            except Exception:
                pass

    if closed_trades:
        async with async_session_factory() as db:
            for trade in closed_trades:
                await db.merge(trade)
            await db.commit()


async def _resolve_stale_pending_trades():
    from app.services.trading.bybit import make_client
    from app.services.trading.credentials import get_bybit_credentials
    from app.services.trading.execution import StopLossFailure, ensure_stop_attached
    from app.services.trading.exchange import find_order_by_client_id
    from app.services.trading.sync import record_trade_close

    cutoff = datetime.now(timezone.utc) - PENDING_TRADE_TIMEOUT
    async with async_session_factory() as db:
        result = await db.execute(
            select(Trade).where(
                Trade.status == TradeStatus.PENDING,
                Trade.created_at < cutoff,
            )
        )
        stale = result.scalars().all()
        if not stale:
            return
        user_ids = {t.user_id for t in stale}
        users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        user_map = {u.id: u for u in users}

    for trade in stale:
        user = user_map.get(trade.user_id)
        credentials = get_bybit_credentials(user) if user else None
        if not credentials or not trade.client_order_id:
            # legacy row: nothing to verify against — cancel loudly, do not guess
            trade.status = TradeStatus.CANCELLED
            logger.error(
                "RECONCILE: trade %s (%s %s user=%s) stuck in PENDING without client_order_id "
                "— marked CANCELLED. Verify on the exchange whether the order exists!",
                trade.id, trade.symbol, trade.side, trade.user_id,
            )
            continue

        exchange = make_client(credentials[0], credentials[1])
        try:
            await exchange.load_markets()
            order = await find_order_by_client_id(exchange, trade.client_order_id, trade.symbol)
        except Exception as e:
            logger.error(
                "RECONCILE: cannot verify trade %s on the exchange (%s) — leaving PENDING",
                trade.id, e,
            )
            continue
        finally:
            try:
                await exchange.close()
            except Exception:
                pass

        if order is None:
            trade.status = TradeStatus.CANCELLED
            logger.error(
                "RECONCILE: trade %s verified absent on the exchange — marked CANCELLED",
                trade.id,
            )
            continue

        order_status = str(order.get("status", "")).lower()
        if order_status in ("closed", "filled", "ok"):
            fill_price = order.get("average") or order.get("price") or float(trade.entry_price)
            trade.status = TradeStatus.OPEN
            trade.order_id = str(order.get("id")) if order.get("id") else None
            trade.entry_price = Decimal(str(round(float(fill_price), 8)))
            logger.error(
                "RECONCILE: trade %s order exists and is FILLED on the exchange — recovering to OPEN",
                trade.id,
            )
            # recovered position must not exist without a stop
            if trade.stop_loss:
                exchange2 = make_client(credentials[0], credentials[1])
                try:
                    await exchange2.load_markets()
                    side = str(trade.side)
                    protective = await ensure_stop_attached(
                        exchange2, trade.symbol, side, float(trade.size),
                        float(trade.stop_loss),
                        float(trade.take_profit) if trade.take_profit else None,
                    )
                    trade.stop_order_id = protective["stop_order_id"]
                    trade.tp_order_id = protective["tp_order_id"]
                except StopLossFailure as e:
                    close_side = "sell" if side == "buy" else "buy"
                    try:
                        close_order = await exchange2.create_order(
                            trade.symbol, "market", close_side, float(trade.size),
                            None, {"reduceOnly": True},
                        )
                        exit_price = float(close_order.get("average") or close_order.get("price") or 0)
                        fee_info = close_order.get("fee") or {}
                        record_trade_close(trade, exit_price, fee_info.get("cost"))
                        logger.critical(
                            "RECONCILE: recovered trade %s had no stop and one could not be "
                            "attached — position closed: %s", trade.id, e,
                        )
                    except Exception as close_error:
                        logger.critical(
                            "RECONCILE: recovered trade %s has NO STOP and emergency close failed: %s",
                            trade.id, close_error,
                        )
                finally:
                    try:
                        await exchange2.close()
                    except Exception:
                        pass
        elif order_status in ("canceled", "cancelled", "expired", "rejected"):
            trade.status = TradeStatus.CANCELLED
            logger.error(
                "RECONCILE: trade %s exists on the exchange with status %s — marked CANCELLED",
                trade.id, order_status,
            )
        else:
            logger.error(
                "RECONCILE: trade %s is %s on the exchange — leaving PENDING",
                trade.id, order_status,
            )
            continue

    async with async_session_factory() as db:
        for trade in stale:
            await db.merge(trade)
        await db.commit()


def start_scheduler() -> list[asyncio.Task]:
    return [
        asyncio.create_task(subscription_maintenance_loop()),
        asyncio.create_task(trade_reconciliation_loop()),
        asyncio.create_task(position_sync_loop()),
        asyncio.create_task(market_context_loop()),
    ]
