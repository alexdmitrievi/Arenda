import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.database import async_session_factory
from app.models.trade import Trade, TradeStatus

logger = logging.getLogger("tbx.trading.journal")


async def record_trade_open(trade: Trade):
    async with async_session_factory() as db:
        db.add(trade)
        await db.commit()
    logger.info("Trade opened: %s %s %s @ %s", trade.symbol, trade.side.value, trade.size, trade.entry_price)


async def record_trade_close(trade_id: str, exit_price: Decimal | float):
    async with async_session_factory() as db:
        result = await db.execute(select(Trade).where(Trade.id == trade_id))
        trade = result.scalar_one_or_none()
        if not trade:
            return

        ep = Decimal(str(exit_price))
        trade.exit_price = ep
        trade.status = TradeStatus.CLOSED
        trade.closed_at = datetime.now(timezone.utc)

        entry = float(trade.entry_price)
        size = float(trade.size)
        exit_p = float(ep)
        pnl = (exit_p - entry) * size
        pnl_pct = (exit_p - entry) / entry * 100 if entry != 0 else 0
        trade.pnl = Decimal(str(round(pnl, 2)))
        trade.pnl_pct = Decimal(str(round(pnl_pct, 2)))

        await db.commit()
    logger.info("Trade closed: %s PnL $%s (%s%%)", trade_id, trade.pnl, trade.pnl_pct)


async def get_trade_stats(user_id: str) -> dict[str, Any]:
    async with async_session_factory() as db:
        total = await db.execute(
            select(func.count(Trade.id)).where(Trade.user_id == user_id)
        )
        closed = await db.execute(
            select(func.count(Trade.id)).where(
                Trade.user_id == user_id, Trade.status == TradeStatus.CLOSED
            )
        )
        wins = await db.execute(
            select(func.count(Trade.id)).where(
                Trade.user_id == user_id,
                Trade.status == TradeStatus.CLOSED,
                Trade.pnl > 0,
            )
        )
        total_pnl = await db.execute(
            select(func.sum(Trade.pnl)).where(Trade.user_id == user_id)
        )
        best = await db.execute(
            select(Trade).where(
                Trade.user_id == user_id, Trade.status == TradeStatus.CLOSED
            ).order_by(Trade.pnl.desc()).limit(1)
        )
        worst = await db.execute(
            select(Trade).where(
                Trade.user_id == user_id, Trade.status == TradeStatus.CLOSED
            ).order_by(Trade.pnl.asc()).limit(1)
        )

        total_count = total.scalar() or 0
        closed_count = closed.scalar() or 0
        win_count = wins.scalar() or 0

        return {
            "total_trades": total_count,
            "closed_trades": closed_count,
            "winning_trades": win_count,
            "win_rate": round(win_count / closed_count * 100, 1) if closed_count > 0 else 0,
            "total_pnl": float(total_pnl.scalar() or 0),
            "best_trade": float(best.scalar_one_or_none().pnl) if best else 0,
            "worst_trade": float(worst.scalar_one_or_none().pnl) if worst else 0,
        }
