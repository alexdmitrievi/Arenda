import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import ccxt.pro as ccxt_pro
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.models.trade import Signal, Strategy, StrategyType
from app.services.strategies.smc import SMCStrategy
from app.services.trading.market_data import cache_ohlcv, set_latest_price

logger = logging.getLogger("tbx.market_data.collector")

TRADE_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"]
TIMEFRAMES = {"1h": "1h"}
LOOKBACK_CANDLES = 500

_smc_strategy: Optional[SMCStrategy] = None


def get_smc_strategy() -> SMCStrategy:
    global _smc_strategy
    if _smc_strategy is None:
        _smc_strategy = SMCStrategy(min_rr_ratio=2.0, min_confidence=50)
    return _smc_strategy


async def _get_or_create_smc_strategy(db: AsyncSession) -> Strategy:
    result = await db.execute(
        select(Strategy).where(Strategy.type == StrategyType.SMC, Strategy.is_active.is_(True))
    )
    strategy = result.scalar_one_or_none()
    if strategy is None:
        strategy = Strategy(
            name="SMC 1H Signals",
            type=StrategyType.SMC,
            params={"min_rr_ratio": 2.0, "min_confidence": 50},
            is_active=True,
        )
        db.add(strategy)
        await db.flush()
    return strategy


async def fetch_historical_ohlcv(exchange: ccxt_pro.Exchange, symbol: str, timeframe: str) -> pd.DataFrame:
    try:
        raw = await exchange.fetch_ohlcv(symbol, timeframe, limit=LOOKBACK_CANDLES)
        if not raw or len(raw) < 50:
            logger.warning("Insufficient OHLCV data for %s: %d candles", symbol, len(raw) if raw else 0)
            return pd.DataFrame()

        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        logger.error("Failed to fetch OHLCV for %s %s: %s", symbol, timeframe, e)
        return pd.DataFrame()


async def generate_and_store_signal(symbol: str, df: pd.DataFrame) -> Optional[Signal]:
    strategy_engine = get_smc_strategy()
    signal_result = strategy_engine.generate_signal(df, symbol.replace("/", "").replace("USDT", ""))

    if signal_result.direction == "NONE" or signal_result.confidence < 50:
        return None

    async with async_session_factory() as db:
        try:
            strategy = await _get_or_create_smc_strategy(db)

            direction_map = {"BUY": "buy", "SELL": "sell", "NONE": "buy"}
            signal = Signal(
                strategy_id=strategy.id,
                symbol=symbol,
                direction=direction_map.get(signal_result.direction, "buy"),
                entry=Decimal(str(round(signal_result.entry, 8))) if signal_result.entry else Decimal("0"),
                stop_loss=Decimal(str(round(signal_result.stop_loss, 8))) if signal_result.stop_loss else Decimal("0"),
                take_profit=[round(tp, 8) for tp in signal_result.take_profit],
                confidence=signal_result.confidence,
                metadata_=signal_result.metadata,
            )
            db.add(signal)
            await db.commit()
            await db.refresh(signal)

            logger.info(
                "Signal stored: %s %s conf=%d entry=%.4f sl=%.4f",
                symbol, signal_result.direction, signal_result.confidence,
                signal_result.entry, signal_result.stop_loss,
            )
            return signal
        except Exception as e:
            await db.rollback()
            logger.error("Failed to store signal for %s: %s", symbol, e)
            return None


async def process_closed_candle(exchange: ccxt_pro.Exchange, symbol: str, candle: list):
    try:
        redis = await get_redis()
        await cache_ohlcv(redis, symbol, "1h", [candle])
        await set_latest_price(redis, symbol, float(candle[4]))

        logger.debug("Candle cached: %s O=%.4f H=%.4f L=%.4f C=%.4f", symbol, *candle[1:5])
    except Exception as e:
        logger.error("Failed to cache candle for %s: %s", symbol, e)

    try:
        df = await fetch_historical_ohlcv(exchange, symbol, "1h")
        if df.empty:
            return

        signal = await generate_and_store_signal(symbol, df)
        if signal:
            await notify_signal(signal)
    except Exception as e:
        logger.error("Signal generation failed for %s: %s", symbol, e)


async def notify_signal(signal: Signal):
    try:
        redis = await get_redis()
        import json
        payload = {
            "id": str(signal.id),
            "symbol": signal.symbol,
            "direction": signal.direction.value if hasattr(signal.direction, 'value') else str(signal.direction),
            "entry": float(signal.entry),
            "stop_loss": float(signal.stop_loss),
            "take_profit": signal.take_profit if isinstance(signal.take_profit, list) else [],
            "confidence": signal.confidence,
            "created_at": signal.created_at.isoformat() if signal.created_at else datetime.now(timezone.utc).isoformat(),
        }
        await redis.publish("signals:new", json.dumps(payload, default=str))
        logger.info("Signal notification published: %s %s", signal.symbol, signal.direction)
    except Exception as e:
        logger.error("Failed to notify signal: %s", e)


async def watch_ohlcv_loop():
    exchange = ccxt_pro.binance({"enableRateLimit": True})
    logger.info("Market Data Collector started. Watching %d symbols: %s", len(TRADE_SYMBOLS), ", ".join(TRADE_SYMBOLS))

    retry_delay = 5
    max_retry_delay = 300

    while True:
        try:
            await _watch(exchange)
        except asyncio.CancelledError:
            logger.info("Market Data Collector cancelled")
            break
        except Exception as e:
            retry_delay = min(retry_delay * 2, max_retry_delay)
            logger.error("Collector error, retrying in %ds: %s", retry_delay, e)
            await asyncio.sleep(retry_delay)
        finally:
            retry_delay = 5


async def _watch(exchange: ccxt_pro.Exchange):
    while True:
        tickers = await exchange.watch_tickers(TRADE_SYMBOLS)
        for symbol, ticker in tickers.items():
            if ticker:
                try:
                    redis = await get_redis()
                    await set_latest_price(redis, symbol, float(ticker.get("last", 0)))
                except Exception:
                    pass


async def start_collector():
    task = asyncio.create_task(watch_ohlcv_loop())
    return task


async def watch_and_signal_loop():
    exchange = ccxt_pro.binance({"enableRateLimit": True})
    logger.info("Signal Engine started. Symbols: %s", ", ".join(TRADE_SYMBOLS))

    retry_delay = 5
    max_retry_delay = 300

    while True:
        try:
            for symbol in TRADE_SYMBOLS:
                await _watch_and_signal_symbol(exchange, symbol)
        except asyncio.CancelledError:
            logger.info("Signal Engine cancelled")
            break
        except Exception as e:
            retry_delay = min(retry_delay * 2, max_retry_delay)
            logger.error("Signal engine error, retrying in %ds: %s", retry_delay, e)
            await asyncio.sleep(retry_delay)


async def _watch_and_signal_symbol(exchange: ccxt_pro.Exchange, symbol: str):
    last_processed_ts = 0

    while True:
        ohlcv = await exchange.watch_ohlcv(symbol, "1h")
        if ohlcv and len(ohlcv) > 0:
            latest = ohlcv[-1]
            candle_ts = latest[0]

            if candle_ts > last_processed_ts and candle_ts > 0:
                last_processed_ts = candle_ts
                await process_closed_candle(exchange, symbol, latest)

        await asyncio.sleep(5)


async def start_signal_engine():
    task = asyncio.create_task(watch_and_signal_loop())
    return task
