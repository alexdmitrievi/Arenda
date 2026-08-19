import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from app.api.deps import ActiveSubscriber, CurrentUser, DbSession, has_active_subscription
from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.core.security import decode_token, decrypt_api_key
from app.models.trade import Signal, Trade, TradeSide, TradeStatus
from app.models.user import User
from app.services.trading.market_data import get_latest_price

logger = logging.getLogger("tbx.api.signals")

router = APIRouter()

# Free accounts see signals with a delay; paid/referral accounts see them live.
FREE_SIGNAL_DELAY = timedelta(hours=24)

# Portfolio-level risk limits for REAL trades (paper is unlimited).
# Crypto alts are heavily correlated — 5 concurrent positions at 2% risk each
# already behave like one ~10% BTC-beta bet, so the cap is deliberately tight.
MAX_OPEN_REAL_TRADES = 5
DAILY_LOSS_LIMIT_PCT = 5.0


async def _check_portfolio_risk(db, user_id, usdt_balance: float):
    open_count = await db.scalar(
        select(func.count())
        .select_from(Trade)
        .where(
            Trade.user_id == user_id,
            Trade.exchange != "paper",
            Trade.status.in_([TradeStatus.PENDING, TradeStatus.OPEN]),
        )
    )
    if (open_count or 0) >= MAX_OPEN_REAL_TRADES:
        raise HTTPException(
            status_code=400,
            detail=f"Risk limit: max {MAX_OPEN_REAL_TRADES} open positions. "
            "Close something before opening a new trade.",
        )

    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    realized_today = await db.scalar(
        select(func.coalesce(func.sum(Trade.pnl), 0)).where(
            Trade.user_id == user_id,
            Trade.exchange != "paper",
            Trade.status == TradeStatus.CLOSED,
            Trade.closed_at >= day_start,
        )
    )
    if usdt_balance > 0 and float(realized_today or 0) <= -usdt_balance * DAILY_LOSS_LIMIT_PCT / 100:
        raise HTTPException(
            status_code=400,
            detail=f"Risk limit: daily loss exceeded {DAILY_LOSS_LIMIT_PCT}% of balance. "
            "Trading is paused until tomorrow (UTC).",
        )


async def _signal_visibility_cutoff(user, db) -> datetime | None:
    """Returns the newest created_at a user may see, or None for full access."""
    if await has_active_subscription(user, db):
        return None
    return datetime.now(timezone.utc) - FREE_SIGNAL_DELAY


@router.get("/signals")
async def get_signals(
    db: DbSession,
    current_user: CurrentUser,
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

    cutoff = await _signal_visibility_cutoff(current_user, db)
    if cutoff is not None:
        query = query.where(Signal.created_at <= cutoff)

    if symbol:
        query = query.where(Signal.symbol == symbol.upper())
    if direction:
        query = query.where(Signal.direction == direction)

    query = query.order_by(desc(Signal.created_at)).limit(limit)
    result = await db.execute(query)
    signals = result.scalars().all()

    return {
        "count": len(signals),
        "delayed": cutoff is not None,
        "signals": [_signal_to_dict(s) for s in signals],
    }


@router.get("/signals/latest")
async def get_latest_signals(
    db: DbSession,
    current_user: CurrentUser,
    limit: int = Query(default=5, ge=1, le=20),
):
    query = select(Signal)

    cutoff = await _signal_visibility_cutoff(current_user, db)
    if cutoff is not None:
        query = query.where(Signal.created_at <= cutoff)

    query = query.order_by(desc(Signal.created_at)).limit(limit)
    result = await db.execute(query)
    signals = result.scalars().all()

    return {
        "count": len(signals),
        "delayed": cutoff is not None,
        "signals": [_signal_to_dict(s) for s in signals],
    }


@router.get("/signals/stream")
async def stream_signals(token: str = Query(min_length=1)):
    """Server-Sent Events stream of new signals.

    EventSource cannot send an Authorization header, so the access token
    arrives as a query parameter. Auth runs in a short-lived session — the
    stream itself must not pin a DB connection for its whole lifetime.
    """
    try:
        payload = decode_token(token)
        user_id = UUID(payload.get("sub") or "")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive")
        if not await has_active_subscription(user, db):
            raise HTTPException(
                status_code=402,
                detail="Real-time stream requires an active subscription",
            )

    async def event_generator():
        redis = await get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe("signals:new")
        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=15
                )
                if message and message.get("type") == "message":
                    yield f"data: {message['data']}\n\n"
                else:
                    yield ": keepalive\n\n"
        finally:
            await pubsub.unsubscribe("signals:new")
            await pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/signals/{signal_id}")
async def get_signal(signal_id: str, db: DbSession, current_user: CurrentUser):
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    cutoff = await _signal_visibility_cutoff(current_user, db)
    if cutoff is not None and signal.created_at and signal.created_at > cutoff:
        raise HTTPException(
            status_code=402,
            detail="Real-time signals require an active subscription",
        )
    return _signal_to_dict(signal)


class ExecuteRequest(BaseModel):
    paper: bool = False


def _decrypted_bybit_keys(user) -> tuple[str, str]:
    user_keys = user.exchange_keys_encrypted or {}
    bybit_keys = user_keys.get("bybit", {})
    api_key = bybit_keys.get("api_key")
    secret = bybit_keys.get("secret")
    if not api_key or not secret:
        raise HTTPException(
            status_code=400,
            detail="Bybit API keys not configured. Add them in settings.",
        )
    return decrypt_api_key(api_key), decrypt_api_key(secret)


def _user_risk_pct(user) -> float:
    bybit_keys = (user.exchange_keys_encrypted or {}).get("bybit", {})
    try:
        return float(bybit_keys.get("risk_per_trade_pct", 2.0))
    except (TypeError, ValueError):
        return 2.0


@router.post("/signals/{signal_id}/execute")
async def execute_signal_endpoint(
    signal_id: str,
    db: DbSession,
    current_user: CurrentUser,
    _: ActiveSubscriber,
    request: ExecuteRequest | None = None,
):
    request = request or ExecuteRequest()

    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    existing = await db.execute(
        select(Trade.id).where(
            Trade.signal_id == signal.id,
            Trade.user_id == current_user.id,
            Trade.status.in_([TradeStatus.PENDING, TradeStatus.OPEN, TradeStatus.CLOSED]),
        ).limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="You already executed this signal")

    entry_price = float(signal.entry)
    stop_loss_price = float(signal.stop_loss)
    stop_distance = abs(entry_price - stop_loss_price)
    if stop_distance <= 0:
        raise HTTPException(status_code=400, detail="Invalid stop-loss distance")

    tp_list = signal.take_profit if isinstance(signal.take_profit, list) else []
    tp_price = float(tp_list[0]) if tp_list else None
    side = "buy" if str(signal.direction) == "buy" or signal.direction == TradeSide.BUY else "sell"

    if request.paper:
        return await _execute_paper(db, current_user, signal, side, entry_price, stop_loss_price, tp_price)

    if side == "sell":
        raise HTTPException(
            status_code=400,
            detail="Short trades are not supported on spot yet. Use paper mode to track this signal.",
        )

    api_key, secret = _decrypted_bybit_keys(current_user)
    risk_pct = _user_risk_pct(current_user)

    import ccxt.async_support as ccxt_async

    exchange = ccxt_async.bybit({
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
    })

    try:
        await exchange.load_markets()

        balance_data = await exchange.fetch_balance()
        usdt_balance = float(balance_data.get("USDT", {}).get("free", 0))

        await _check_portfolio_risk(db, current_user.id, usdt_balance)

        risk_amount = usdt_balance * (risk_pct / 100)
        position_size_base = round(risk_amount / stop_distance, 6)
        if position_size_base <= 0:
            raise HTTPException(status_code=400, detail="Position size too small")

        # 1) persist intent BEFORE touching the exchange — a crash after the
        #    order leaves a PENDING row the reconciliation loop will flag,
        #    never a position that the system does not know about
        trade = Trade(
            user_id=current_user.id,
            exchange="bybit",
            symbol=signal.symbol,
            side=TradeSide.BUY,
            strategy_id=signal.strategy_id,
            signal_id=signal.id,
            entry_price=Decimal(str(entry_price)),
            size=Decimal(str(position_size_base)),
            status=TradeStatus.PENDING,
        )
        db.add(trade)
        await db.commit()
        await db.refresh(trade)

        # 2) one atomic order: SL/TP attached at creation, not as a
        #    second request that can silently fail
        order_params: dict = {"stopLoss": stop_loss_price}
        if tp_price:
            order_params["takeProfit"] = tp_price

        try:
            order = await exchange.create_order(
                signal.symbol, "market", side, position_size_base, None, order_params
            )
        except Exception as e:
            trade.status = TradeStatus.CANCELLED
            await db.commit()
            logger.error("Order placement failed for trade %s: %s", trade.id, e)
            raise HTTPException(status_code=502, detail=f"Exchange rejected order: {str(e)[:200]}")

        # 3) confirm with real fill data
        fill_price = order.get("average") or order.get("price") or entry_price
        fee_info = order.get("fee") or {}
        trade.status = TradeStatus.OPEN
        trade.order_id = str(order.get("id")) if order.get("id") else None
        trade.entry_price = Decimal(str(fill_price))
        if fee_info.get("cost") is not None:
            trade.fee = Decimal(str(fee_info["cost"]))
        signal.executed = True
        await db.commit()

        return {
            "status": "executed",
            "trade_id": str(trade.id),
            "symbol": signal.symbol,
            "direction": side,
            "entry_price": float(fill_price),
            "stop_loss": stop_loss_price,
            "take_profit": tp_price,
            "position_size": position_size_base,
            "risk_amount": round(risk_amount, 2),
            "paper": False,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Execution failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)[:200]}")
    finally:
        try:
            await exchange.close()
        except Exception:
            pass


async def _execute_paper(db, user, signal, side: str, entry_price: float,
                         stop_loss_price: float, tp_price: float | None):
    redis = await get_redis()
    market_price = await get_latest_price(redis, signal.symbol)
    fill_price = market_price or entry_price

    # fixed notional keeps paper results comparable across users
    paper_balance = 10000.0
    risk_amount = paper_balance * 0.02
    stop_distance = abs(fill_price - stop_loss_price) or fill_price * 0.01
    size = round(risk_amount / stop_distance, 6)

    trade = Trade(
        user_id=user.id,
        exchange="paper",
        symbol=signal.symbol,
        side=TradeSide.BUY if side == "buy" else TradeSide.SELL,
        strategy_id=signal.strategy_id,
        signal_id=signal.id,
        entry_price=Decimal(str(fill_price)),
        size=Decimal(str(size)),
        status=TradeStatus.OPEN,
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)

    return {
        "status": "executed",
        "trade_id": str(trade.id),
        "symbol": signal.symbol,
        "direction": side,
        "entry_price": fill_price,
        "stop_loss": stop_loss_price,
        "take_profit": tp_price,
        "position_size": size,
        "risk_amount": round(risk_amount, 2),
        "paper": True,
    }


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
                "exchange": t.exchange,
                "entry_price": float(t.entry_price),
                "exit_price": float(t.exit_price) if t.exit_price else None,
                "size": float(t.size),
                "pnl": float(t.pnl) if t.pnl else None,
                "pnl_pct": float(t.pnl_pct) if t.pnl_pct else None,
                "fee": float(t.fee) if t.fee else None,
                "status": str(t.status),
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in trades
        ],
    }


def _record_close(trade: Trade, exit_price: float, fee_cost: float | None = None):
    trade.status = TradeStatus.CLOSED
    trade.closed_at = datetime.now(timezone.utc)
    trade.exit_price = Decimal(str(exit_price))

    entry = float(trade.entry_price)
    size = float(trade.size)
    direction = 1 if str(trade.side) == "buy" or trade.side == TradeSide.BUY else -1
    pnl = (exit_price - entry) * size * direction
    if fee_cost:
        pnl -= fee_cost
        trade.fee = (trade.fee or Decimal("0")) + Decimal(str(fee_cost))
    trade.pnl = Decimal(str(round(pnl, 2)))
    notional = entry * size
    if notional > 0:
        trade.pnl_pct = Decimal(str(round(pnl / notional * 100, 2)))


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

    if trade.exchange == "paper":
        redis = await get_redis()
        market_price = await get_latest_price(redis, trade.symbol)
        exit_price = market_price or float(trade.entry_price)
        _record_close(trade, exit_price)
        await db.commit()
        return {
            "status": "closed",
            "trade_id": str(trade.id),
            "symbol": trade.symbol,
            "exit_price": exit_price,
            "pnl": float(trade.pnl) if trade.pnl else 0.0,
        }

    api_key, secret = _decrypted_bybit_keys(current_user)

    import ccxt.async_support as ccxt_async

    exchange = ccxt_async.bybit({
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
    })

    try:
        await exchange.load_markets()

        close_side = "sell" if str(trade.side) == "buy" else "buy"
        order = await exchange.create_order(trade.symbol, "market", close_side, float(trade.size))

        exit_price = float(order.get("average") or order.get("price") or 0)
        if exit_price <= 0:
            ticker = await exchange.fetch_ticker(trade.symbol)
            exit_price = float(ticker.get("last") or trade.entry_price)

        fee_info = order.get("fee") or {}
        _record_close(trade, exit_price, fee_info.get("cost"))
        await db.commit()

        return {
            "status": "closed",
            "trade_id": str(trade.id),
            "symbol": trade.symbol,
            "exit_price": exit_price,
            "pnl": float(trade.pnl) if trade.pnl else 0.0,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Close position failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Close failed: {str(e)[:200]}")
    finally:
        try:
            await exchange.close()
        except Exception:
            pass


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
        "metadata": s.metadata_ or {},
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
