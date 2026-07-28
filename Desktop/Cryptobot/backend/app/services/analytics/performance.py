from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.database import async_session_factory
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.trade import Trade, TradeStatus
from app.models.user import User


async def get_overview_stats() -> dict[str, Any]:
    async with async_session_factory() as db:
        total_users = await db.execute(select(func.count(User.id)))
        active_subs = await db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL])
            )
        )
        total_trades = await db.execute(select(func.count(Trade.id)))
        winning_trades = await db.execute(
            select(func.count(Trade.id)).where(
                Trade.status == TradeStatus.CLOSED, Trade.pnl > 0
            )
        )

        return {
            "total_users": total_users.scalar() or 0,
            "active_subscriptions": active_subs.scalar() or 0,
            "total_trades": total_trades.scalar() or 0,
            "winning_trades": winning_trades.scalar() or 0,
        }


async def get_pnl_report(user_id: str, days: int = 30) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session_factory() as db:
        result = await db.execute(
            select(Trade).where(
                Trade.user_id == user_id,
                Trade.status == TradeStatus.CLOSED,
                Trade.closed_at >= cutoff,
            ).order_by(Trade.closed_at.desc())
        )
        trades = result.scalars().all()

        total_pnl = sum(float(t.pnl or 0) for t in trades)
        win_count = sum(1 for t in trades if float(t.pnl or 0) > 0)
        total_count = len(trades)

        return {
            "period_days": days,
            "total_trades": total_count,
            "winning_trades": win_count,
            "losing_trades": total_count - win_count,
            "win_rate": round(win_count / total_count * 100, 1) if total_count > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_per_trade": round(total_pnl / total_count, 2) if total_count > 0 else 0,
            "trades": [
                {
                    "symbol": t.symbol,
                    "side": t.side.value,
                    "entry": float(t.entry_price),
                    "exit": float(t.exit_price) if t.exit_price else None,
                    "pnl": float(t.pnl) if t.pnl else 0,
                    "pnl_pct": float(t.pnl_pct) if t.pnl_pct else 0,
                    "closed_at": t.closed_at.isoformat() if t.closed_at else None,
                }
                for t in trades[:50]
            ],
        }


async def get_user_metrics(user_id: str) -> dict[str, Any]:
    async with async_session_factory() as db:
        result = await db.execute(
            select(Trade).where(Trade.user_id == user_id, Trade.status == TradeStatus.CLOSED)
        )
        trades = result.scalars().all()

        if not trades:
            return {"message": "No closed trades yet"}

        pnls = [float(t.pnl or 0) for t in trades]
        total_pnl = sum(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [abs(p) for p in pnls if p <= 0]
        win_count = len(wins)
        total_count = len(pnls)

        gross_profit = sum(wins)
        gross_loss = sum(losses) or 0.01

        running_sum = 0
        peak = 0
        max_dd = 0
        for p in pnls:
            running_sum += p
            peak = max(peak, running_sum)
            max_dd = max(max_dd, peak - running_sum)

        return {
            "total_trades": total_count,
            "win_rate": round(win_count / total_count * 100, 1),
            "profit_factor": round(gross_profit / gross_loss, 2),
            "total_pnl": round(total_pnl, 2),
            "best_trade": round(max(pnls), 2) if pnls else 0,
            "worst_trade": round(min(pnls), 2) if pnls else 0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "max_drawdown": round(max_dd, 2),
        }
