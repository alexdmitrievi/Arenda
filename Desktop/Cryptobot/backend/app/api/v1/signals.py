from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActiveSubscriber, CurrentUser, DbSession
from app.models.trade import Signal, Trade, TradeSide, TradeStatus
from app.models.user import User
from app.core.database import async_session_factory
from app.core.security import decrypt_api_key

import logging

logger = logging.getLogger("tbx.api.signals")

router = APIRouter()


@router.get("/signals")
async def get_signals(
    db: DbSession,
    symbol: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    min_confidence: int = Query(default=50, ge=0, le=100),
    limit: int = Query(default=20, ge=1, le=100),
    hours: int = Query(default=24, ge=1, le=168),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    query = select(Signal).where(
        Signal.created_at >= since,
        Signal.confidence >= min_confidence,
    )

    if symbol:
        query = query.where(Signal.symbol == symbol.upper())
    if direction:
        query = query.where(Signal.direction == direction)

    query = query.order_by(desc(Signal.created_at)).limit(limit)
    result = await db.execute(query)
    signals = result.scalars().all()

    return {
        "count": len(signals),
        "signals": [_signal_to_dict(s) for s in signals],
    }


@router.get("/signals/latest")
async def get_latest_signals(
    db: DbSession,
    limit: int = Query(default=5, ge=1, le=20),
):
    query = (
        select(Signal)
        .order_by(desc(Signal.created_at))
        .limit(limit)
    )
    result = await db.execute(query)
    signals = result.scalars().all()

    return {
        "count": len(signals),
        "signals": [_signal_to_dict(s) for s in signals],
    }


@router.get("/signals/{signal_id}")
async def get_signal(signal_id: str, db: DbSession):
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return _signal_to_dict(signal)


@router.post("/signals/{signal_id}/execute")
async def execute_signal_endpoint(
    signal_id: str,
    db: DbSession,
    current_user: CurrentUser,
    _: ActiveSubscriber,
):
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()

    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    if signal.executed:
        raise HTTPException(status_code=400, detail="Signal already executed")

    user_keys = current_user.exchange_keys_encrypted or {}
    bybit_keys = user_keys.get("bybit", {})
    bybit_api_key = bybit_keys.get("api_key")
    bybit_secret = bybit_keys.get("secret")

    if not bybit_api_key or not bybit_secret:
        raise HTTPException(status_code=400, detail="Bybit API keys not configured. Add them in settings.")

    try:
        import ccxt.async_support as ccxt_async

        exchange = ccxt_async.bybit({
            "apiKey": decrypt_api_key(bybit_api_key),
            "secret": decrypt_api_key(bybit_secret),
            "enableRateLimit": True,
        })
        await exchange.load_markets()

        balance_data = await exchange.fetch_balance()
        usdt_balance = float(balance_data.get("USDT", {}).get("free", 0))

        risk_pct = float(bybit_keys.get("risk_per_trade_pct", 2.0))
        entry_price = float(signal.entry)
        stop_loss_price = float(signal.stop_loss)
        stop_distance = abs(entry_price - stop_loss_price)

        if stop_distance <= 0:
            await exchange.close()
            raise HTTPException(status_code=400, detail="Invalid stop-loss distance")

        risk_amount = usdt_balance * (risk_pct / 100)
        position_size_base = risk_amount / stop_distance
        position_size_base = round(position_size_base, 6)

        if position_size_base <= 0:
            await exchange.close()
            raise HTTPException(status_code=400, detail="Position size too small")

        side = "buy" if str(signal.direction) == "buy" else "sell"
        order = await exchange.create_order(
            signal.symbol, "market", side, position_size_base
        )

        trade = Trade(
            user_id=current_user.id,
            exchange="bybit",
            symbol=signal.symbol,
            side=TradeSide.BUY if side == "buy" else TradeSide.SELL,
            strategy_id=signal.strategy_id,
            signal_id=signal.id,
            entry_price=Decimal(str(entry_price)),
            size=Decimal(str(position_size_base)),
            status=TradeStatus.OPEN,
        )
        signal.executed = True

        db.add(trade)
        db.add(signal)
        await db.commit()
        await db.refresh(trade)

        tp_price = signal.take_profit[0] if signal.take_profit and isinstance(signal.take_profit, list) else None
        if tp_price:
            try:
                close_side = "sell" if side == "buy" else "buy"
                await exchange.create_order(
                    signal.symbol, "stop_loss", close_side, position_size_base, None,
                    {"stopLossPrice": stop_loss_price, "takeProfitPrice": tp_price}
                )
            except Exception as e:
                logger.warning("Failed to place SL/TP: %s", e)

        await exchange.close()

        return {
            "status": "executed",
            "trade_id": str(trade.id),
            "symbol": signal.symbol,
            "direction": str(signal.direction),
            "entry_price": entry_price,
            "stop_loss": stop_loss_price,
            "take_profit": tp_price,
            "position_size": position_size_base,
            "risk_amount": round(risk_amount, 2),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Execution failed: %s", e)
        try:
            await exchange.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)[:200]}")


@router.get("/positions")
async def get_positions(
    db: DbSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(Trade).where(
            Trade.user_id == current_user.id,
            Trade.status == TradeStatus.OPEN,
        ).order_by(desc(Trade.created_at))
    )
    open_trades = result.scalars().all()

    return {
        "count": len(open_trades),
        "positions": [
            {
                "id": str(t.id),
                "symbol": t.symbol,
                "exchange": t.exchange,
                "side": str(t.side),
                "entry_price": float(t.entry_price),
                "size": float(t.size),
                "pnl": float(t.pnl) if t.pnl else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in open_trades
        ],
    }


@router.get("/trades")
async def get_trade_history(
    db: DbSession,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
):
    result = await db.execute(
        select(Trade).where(
            Trade.user_id == current_user.id,
        ).order_by(desc(Trade.created_at)).limit(limit)
    )
    trades = result.scalars().all()

    return {
        "count": len(trades),
        "trades": [
            {
                "id": str(t.id),
                "symbol": t.symbol,
                "side": str(t.side),
                "entry_price": float(t.entry_price),
                "exit_price": float(t.exit_price) if t.exit_price else None,
                "size": float(t.size),
                "pnl": float(t.pnl) if t.pnl else None,
                "pnl_pct": float(t.pnl_pct) if t.pnl_pct else None,
                "status": str(t.status),
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in trades
        ],
    }


@router.post("/positions/{trade_id}/close")
async def close_position(
    trade_id: str,
    db: DbSession,
    current_user: CurrentUser,
    _: ActiveSubscriber,
):
    result = await db.execute(
        select(Trade).where(Trade.id == trade_id, Trade.user_id == current_user.id)
    )
    trade = result.scalar_one_or_none()

    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.status != TradeStatus.OPEN:
        raise HTTPException(status_code=400, detail="Trade is not open")

    user_keys = current_user.exchange_keys_encrypted or {}
    bybit_keys = user_keys.get("bybit", {})
    bybit_api_key = bybit_keys.get("api_key")

    if not bybit_api_key:
        raise HTTPException(status_code=400, detail="Bybit API keys not configured")

    try:
        import ccxt.async_support as ccxt_async

        exchange = ccxt_async.bybit({
            "apiKey": decrypt_api_key(bybit_api_key),
            "secret": decrypt_api_key(bybit_keys.get("secret", "")),
            "enableRateLimit": True,
        })
        await exchange.load_markets()

        close_side = "sell" if str(trade.side) == "buy" else "buy"
        await exchange.create_order(trade.symbol, "market", close_side, float(trade.size))

        trade.status = TradeStatus.CLOSED
        trade.closed_at = datetime.now(timezone.utc)

        from datetime import datetime as dt
        await db.commit()

        await exchange.close()

        return {
            "status": "closed",
            "trade_id": str(trade.id),
            "symbol": trade.symbol,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Close position failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Close failed: {str(e)[:200]}")


def _signal_to_dict(s: Signal) -> dict:
    return {
        "id": str(s.id),
        "symbol": s.symbol,
        "direction": str(s.direction),
        "entry": float(s.entry),
        "stop_loss": float(s.stop_loss),
        "take_profit": s.take_profit if isinstance(s.take_profit, list) else [],
        "confidence": s.confidence,
        "executed": s.executed,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
