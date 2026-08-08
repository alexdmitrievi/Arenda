import logging
from decimal import Decimal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import ActiveSubscriber, CurrentUser, DbSession
from app.core.redis import get_redis
from app.core.security import decrypt_api_key
from app.models.trade import Trade, TradeSide, TradeStatus
from app.services.market_context.engine import load_context
from app.services.strategies.dca_smart import DCA_ASSETS, build_plan

logger = logging.getLogger("tbx.api.invest")

router = APIRouter()

DAILY_CANDLES_CACHE_TTL = 3600


async def _daily_closes(symbols: list[str]) -> dict[str, pd.Series]:
    """Daily closes per symbol from public Binance data, cached in Redis for 1h."""
    import json

    import ccxt.async_support as ccxt_async

    redis = await get_redis()
    result: dict[str, pd.Series] = {}
    missing: list[str] = []

    for symbol in symbols:
        cached = await redis.get(f"dca:closes:{symbol}")
        if cached:
            result[symbol] = pd.Series(json.loads(cached))
        else:
            missing.append(symbol)

    if missing:
        exchange = ccxt_async.binance({"enableRateLimit": True})
        try:
            for symbol in missing:
                try:
                    raw = await exchange.fetch_ohlcv(symbol, "1d", limit=400)
                    closes = [c[4] for c in raw]
                    result[symbol] = pd.Series(closes)
                    await redis.set(
                        f"dca:closes:{symbol}", json.dumps(closes), ex=DAILY_CANDLES_CACHE_TTL
                    )
                except Exception as e:
                    logger.warning("DCA closes fetch failed for %s: %s", symbol, e)
        finally:
            await exchange.close()

    return result


def _plan_to_dict(plan) -> list[dict]:
    return [
        {
            "symbol": p.symbol,
            "weight": p.weight,
            "multiplier": p.multiplier,
            "amount_usd": p.amount_usd,
            "price": p.price,
            "reasons": p.reasons,
        }
        for p in plan
    ]


@router.get("/dca/recommendation")
async def dca_recommendation(
    current_user: CurrentUser,
    budget: float = Query(default=100.0, ge=10, le=100000),
):
    """What to buy this week: budget split by valuation multipliers and
    altseason-aware allocation."""
    closes = await _daily_closes(DCA_ASSETS)
    if not closes:
        raise HTTPException(status_code=503, detail="Market data temporarily unavailable")

    context = await load_context() or {}
    altseason = (context.get("altseason") or {}).get("score")

    plan = build_plan(budget, closes, altseason)
    total = round(sum(p.amount_usd for p in plan), 2)
    return {
        "budget_usd": budget,
        "total_usd": total,
        "altseason_score": altseason,
        "cycle_phase": (context.get("cycle") or {}).get("phase"),
        "note": (
            "Сумма к покупке масштабируется от 0.25x до 3x бюджета: "
            "чем дешевле актив к своей истории, тем больше покупаем."
        ),
        "plan": _plan_to_dict(plan),
    }


class DCAExecuteRequest(BaseModel):
    budget: float = Field(ge=10, le=100000)
    paper: bool = True


@router.post("/dca/execute")
async def dca_execute(
    request: DCAExecuteRequest,
    current_user: CurrentUser,
    db: DbSession,
    _: ActiveSubscriber,
):
    """Executes the current DCA recommendation: paper by default, real spot
    market buys on Bybit when paper=false."""
    closes = await _daily_closes(DCA_ASSETS)
    if not closes:
        raise HTTPException(status_code=503, detail="Market data temporarily unavailable")

    context = await load_context() or {}
    altseason = (context.get("altseason") or {}).get("score")
    plan = build_plan(request.budget, closes, altseason)
    executed = []

    if request.paper:
        for p in plan:
            if p.amount_usd <= 0:
                continue
            size = round(p.amount_usd / p.price, 8)
            trade = Trade(
                user_id=current_user.id,
                exchange="paper",
                symbol=p.symbol,
                side=TradeSide.BUY,
                entry_price=Decimal(str(p.price)),
                size=Decimal(str(size)),
                status=TradeStatus.OPEN,
            )
            db.add(trade)
            executed.append({"symbol": p.symbol, "amount_usd": p.amount_usd, "paper": True})
        await db.commit()
        return {"status": "executed", "paper": True, "orders": executed}

    user_keys = current_user.exchange_keys_encrypted or {}
    bybit_keys = user_keys.get("bybit", {})
    if not bybit_keys.get("api_key") or not bybit_keys.get("secret"):
        raise HTTPException(status_code=400, detail="Bybit API keys not configured")

    import ccxt.async_support as ccxt_async

    exchange = ccxt_async.bybit({
        "apiKey": decrypt_api_key(bybit_keys["api_key"]),
        "secret": decrypt_api_key(bybit_keys["secret"]),
        "enableRateLimit": True,
        "options": {"createMarketBuyOrderRequiresPrice": False},
    })
    try:
        await exchange.load_markets()
        for p in plan:
            if p.amount_usd <= 0:
                continue
            try:
                # cost-based market buy: spend N USDT
                order = await exchange.create_order(
                    p.symbol, "market", "buy", p.amount_usd
                )
                fill_price = float(order.get("average") or p.price)
                filled = float(order.get("filled") or (p.amount_usd / fill_price))
                trade = Trade(
                    user_id=current_user.id,
                    exchange="bybit",
                    symbol=p.symbol,
                    side=TradeSide.BUY,
                    entry_price=Decimal(str(fill_price)),
                    size=Decimal(str(filled)),
                    status=TradeStatus.OPEN,
                    order_id=str(order.get("id")) if order.get("id") else None,
                )
                db.add(trade)
                executed.append({
                    "symbol": p.symbol, "amount_usd": p.amount_usd,
                    "fill_price": fill_price, "paper": False,
                })
            except Exception as e:
                logger.error("DCA order failed for %s: %s", p.symbol, e)
                executed.append({"symbol": p.symbol, "error": str(e)[:120]})
        await db.commit()
    finally:
        try:
            await exchange.close()
        except Exception:
            pass

    return {"status": "executed", "paper": False, "orders": executed}
