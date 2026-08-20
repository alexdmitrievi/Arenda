import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from app.api.deps import ActiveSubscriber, CurrentUser, DbSession, has_active_subscription
from app.config import settings
from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.core.security import decode_token
from app.models.trade import Signal, Trade, TradeSide, TradeStatus
from app.models.user import User
from app.services.trading.credentials import get_bybit_credentials, user_risk_pct
from app.services.trading.bybit import make_client, perp_symbol, prepare_symbol
from app.services.trading.execution import (
    StopLossFailure,
    compute_position_size,
    ensure_stop_attached,
    position_metrics,
    validate_geometry,
)
from app.services.trading.killswitch import is_trading_halted
from app.services.trading.sync import record_trade_close
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
    credentials = get_bybit_credentials(user)
    if not credentials:
        raise HTTPException(
            status_code=400,
            detail="Bybit API keys not configured. Add them in settings.",
        )
    return credentials


def _user_risk_pct(user) -> float:
    return user_risk_pct(user)


@router.post("/signals/{signal_id}/execute")
async def execute_signal_endpoint(
    signal_id: str,
    db: DbSession,
    current_user: CurrentUser,
    _: ActiveSubscriber,
    request: ExecuteRequest | None = None,
):
    request = request or ExecuteRequest()

    if await is_trading_halted():
        raise HTTPException(
            status_code=503,
            detail="Trading is halted by the operator kill switch. Try again later.",
        )

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

    # product mandate: at least 3:1 reward-to-risk, checked before touching the exchange
    try:
        validate_geometry(entry_price, stop_loss_price, tp_price)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if request.paper:
        return await _execute_paper(db, current_user, signal, side, entry_price, stop_loss_price, tp_price)

    if side == "sell":
        raise HTTPException(
            status_code=400,
            detail="SELL execution is disabled by the owner decision (BUY-only). "
            "Use paper mode to track this signal.",
        )

    api_key, secret = _decrypted_bybit_keys(current_user)
    risk_pct = _user_risk_pct(current_user)

    exchange = make_client(api_key, secret)

    try:
        await exchange.load_markets()

        # USDT-M perpetual futures: 'BTC/USDT' -> 'BTC/USDT:USDT'
        symbol = perp_symbol(signal.symbol)

        balance_data = await exchange.fetch_balance()
        usdt_balance = float(balance_data.get("USDT", {}).get("free", 0))

        await _check_portfolio_risk(db, current_user.id, usdt_balance)

        # product mandate: 2% of deposit risked per trade, sized from the
        # stop zone — leverage never enters the formula
        try:
            position_size_base = compute_position_size(
                usdt_balance, risk_pct, entry_price, stop_loss_price
            )
            metrics = position_metrics(
                entry_price, stop_loss_price, tp_price,
                usdt_balance, risk_pct, leverage=settings.BYBIT_LEVERAGE,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if position_size_base <= 0:
            raise HTTPException(status_code=400, detail="Position size too small")

        # platform margin/leverage policy before any order touches the book
        await prepare_symbol(exchange, symbol)
        order_amount = float(exchange.amount_to_precision(symbol, position_size_base))
        if order_amount <= 0:
            raise HTTPException(status_code=400, detail="Position size rounds to zero on this market")

        # 1) persist intent BEFORE touching the exchange — a crash after the
        #    order leaves a PENDING row the reconciliation loop will resolve
        #    via client_order_id, never a position the system loses track of
        client_order_id = str(uuid4())
        trade = Trade(
            user_id=current_user.id,
            exchange="bybit",
            symbol=symbol,
            side=TradeSide.BUY,
            strategy_id=signal.strategy_id,
            signal_id=signal.id,
            entry_price=Decimal(str(entry_price)),
            size=Decimal(str(order_amount)),
            status=TradeStatus.PENDING,
            client_order_id=client_order_id,
            stop_loss=Decimal(str(stop_loss_price)),
            take_profit=Decimal(str(tp_price)) if tp_price else None,
        )
        db.add(trade)
        await db.commit()
        await db.refresh(trade)

        # 2) one atomic order: SL/TP attached at creation, not as a
        #    second request that can silently fail
        order_params: dict = {"stopLoss": stop_loss_price, "clientOrderId": client_order_id}
        if tp_price:
            order_params["takeProfit"] = tp_price

        try:
            order = await exchange.create_order(
                symbol, "market", side, order_amount, None, order_params
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

        # 4) invariant: no position may exist without a stop-loss. The stop
        #    was requested in the same order; now verify it actually exists
        #    on the exchange, placing it separately if the exchange ignored
        #    the parameter. If it cannot be attached — close immediately.
        try:
            protective = await ensure_stop_attached(
                exchange, symbol, side, order_amount,
                stop_loss_price, tp_price,
            )
        except StopLossFailure as e:
            logger.critical(
                "Trade %s (%s) has no stop-loss and one cannot be attached: %s — closing position",
                trade.id, symbol, e,
            )
            await _emergency_close_trade(exchange, trade, db)
            raise HTTPException(
                status_code=502,
                detail=f"Stop-loss could not be attached, position was closed: {str(e)[:200]}",
            )
        trade.stop_order_id = protective["stop_order_id"]
        trade.tp_order_id = protective["tp_order_id"]

        signal.executed = True
        await db.commit()

        return {
            "status": "executed",
            "trade_id": str(trade.id),
            "symbol": symbol,
            "direction": side,
            "entry_price": float(fill_price),
            "stop_loss": stop_loss_price,
            "take_profit": tp_price,
            "position_size": order_amount,
            "risk": metrics,
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
    metrics = position_metrics(
        fill_price, stop_loss_price, tp_price,
        paper_balance, 2.0, leverage=settings.BYBIT_LEVERAGE,
    )

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
        stop_loss=Decimal(str(stop_loss_price)),
        take_profit=Decimal(str(tp_price)) if tp_price else None,
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
        "risk": metrics,
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
    record_trade_close(trade, exit_price, fee_cost)


async def _emergency_close_trade(exchange, trade: Trade, db) -> bool:
    """Market-close a perp position whose stop-loss could not be attached.

    Returns True when the exchange confirms the close and the DB was updated.
    """
    close_side = "sell" if str(trade.side) == "buy" else "buy"
    try:
        order = await exchange.create_order(
            trade.symbol, "market", close_side, float(trade.size),
            None, {"reduceOnly": True},
        )
        exit_price = float(order.get("average") or order.get("price") or 0)
        if exit_price <= 0:
            ticker = await exchange.fetch_ticker(trade.symbol)
            exit_price = float(ticker.get("last") or trade.entry_price)
        fee_info = order.get("fee") or {}
        record_trade_close(trade, exit_price, fee_info.get("cost"))
        await db.commit()
        logger.critical("Emergency close of trade %s done at %.4f", trade.id, exit_price)
        return True
    except Exception as e:
        logger.critical(
            "Emergency close of trade %s FAILED — position may exist without a stop: %s",
            trade.id, e,
        )
        return False


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
    exchange = make_client(api_key, secret)

    try:
        await exchange.load_markets()

        close_side = "sell" if str(trade.side) == "buy" else "buy"
        order = await exchange.create_order(
            trade.symbol, "market", close_side, float(trade.size),
            None, {"reduceOnly": True},
        )

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
    from app.services.trading.execution import stop_zone_and_rr

    zone, rr = stop_zone_and_rr(
        float(s.entry), float(s.stop_loss),
        float(s.take_profit[0]) if s.take_profit else None,
    )
    return {
        "id": str(s.id),
        "symbol": s.symbol,
        "direction": str(s.direction),
        "entry": float(s.entry),
        "stop_loss": float(s.stop_loss),
        "take_profit": s.take_profit if isinstance(s.take_profit, list) else [],
        "confidence": s.confidence,
        "stop_zone_pct": zone,
        "rr": rr,
        "executed": s.executed,
        "metadata": s.metadata_ or {},
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
