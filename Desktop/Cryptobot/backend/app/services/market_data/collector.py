import asyncio
import json
import logging
import time
from collections import deque
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
TIMEFRAME = "1h"
HTF_TIMEFRAME = "4h"  # higher-timeframe bias for signal confirmation
HTF_CANDLES = 200
HTF_REFRESH_SECONDS = 4 * 3600
LOOKBACK_CANDLES = 500
MAX_RETRY_DELAY = 300

_smc_strategy: Optional[SMCStrategy] = None


def get_smc_strategy() -> SMCStrategy:
    global _smc_strategy
    if _smc_strategy is None:
        _smc_strategy = SMCStrategy(min_rr_ratio=2.0, min_confidence=50)
    return _smc_strategy


class CandleBuffer:
    """In-memory store of closed candles per symbol.

    Seeded once over REST, then maintained from the WebSocket stream, so
    signal generation never needs a REST round-trip per candle.
    """

    def __init__(self, maxlen: int = LOOKBACK_CANDLES):
        self.candles: deque[list] = deque(maxlen=maxlen)

    def seed(self, raw: list[list]) -> None:
        self.candles.clear()
        # the last element is the still-forming candle — keep closed ones only
        for candle in raw[:-1]:
            self.candles.append(candle)

    def append_closed(self, candle: list) -> None:
        if self.candles and self.candles[-1][0] == candle[0]:
            self.candles[-1] = candle
        else:
            self.candles.append(candle)

    def __len__(self) -> int:
        return len(self.candles)

    def to_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame(
            list(self.candles),
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df


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


async def fetch_historical_ohlcv(exchange: ccxt_pro.Exchange, symbol: str, timeframe: str) -> list[list]:
    try:
        raw = await exchange.fetch_ohlcv(symbol, timeframe, limit=LOOKBACK_CANDLES)
        if not raw or len(raw) < 50:
            logger.warning("Insufficient OHLCV data for %s: %d candles", symbol, len(raw) if raw else 0)
            return []
        return raw
    except Exception as e:
        logger.error("Failed to fetch OHLCV for %s %s: %s", symbol, timeframe, e)
        return []


async def generate_and_store_signal(symbol: str, df: pd.DataFrame,
                                    htf_df: Optional[pd.DataFrame] = None) -> Optional[Signal]:
    strategy_engine = get_smc_strategy()
    signal_result = strategy_engine.generate_signal(df, symbol, htf_df=htf_df)

    if signal_result.direction == "NONE" or signal_result.confidence < 50:
        return None

    async with async_session_factory() as db:
        try:
            strategy = await _get_or_create_smc_strategy(db)

            direction_map = {"BUY": "buy", "SELL": "sell"}
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


async def process_closed_candle(symbol: str, candle: list, buffer: CandleBuffer,
                                htf_df: Optional[pd.DataFrame] = None):
    try:
        redis = await get_redis()
        await cache_ohlcv(redis, symbol, TIMEFRAME, list(buffer.candles)[-100:])
        await set_latest_price(redis, symbol, float(candle[4]))
    except Exception as e:
        logger.error("Failed to cache candle for %s: %s", symbol, e)

    if len(buffer) < 50:
        return

    try:
        signal = await generate_and_store_signal(symbol, buffer.to_dataframe(), htf_df)
        if signal:
            await notify_signal(signal)
    except Exception as e:
        logger.error("Signal generation failed for %s: %s", symbol, e)


async def notify_signal(signal: Signal):
    try:
        redis = await get_redis()
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


async def watch_tickers_loop():
    """Keeps latest prices in Redis for the UI and paper trading."""
    exchange = ccxt_pro.binance({"enableRateLimit": True})
    logger.info("Ticker collector started for %d symbols", len(TRADE_SYMBOLS))

    retry_delay = 5
    try:
        while True:
            started = time.monotonic()
            try:
                await _watch_tickers(exchange)
            except asyncio.CancelledError:
                logger.info("Ticker collector cancelled")
                break
            except Exception as e:
                if time.monotonic() - started > 600:
                    retry_delay = 5
                logger.error("Ticker collector error, retrying in %ds: %s", retry_delay, e)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
    finally:
        await exchange.close()


async def _watch_tickers(exchange: ccxt_pro.Exchange):
    while True:
        tickers = await exchange.watch_tickers(TRADE_SYMBOLS)
        redis = await get_redis()
        for symbol, ticker in tickers.items():
            if ticker and ticker.get("last"):
                try:
                    await set_latest_price(redis, symbol, float(ticker["last"]))
                except Exception:
                    pass


async def start_collector():
    return asyncio.create_task(watch_tickers_loop())


async def watch_and_signal_loop():
    exchange = ccxt_pro.binance({"enableRateLimit": True})
    logger.info("Signal Engine started. Symbols: %s", ", ".join(TRADE_SYMBOLS))
    try:
        await asyncio.gather(*(_symbol_loop(exchange, s) for s in TRADE_SYMBOLS))
    finally:
        await exchange.close()


async def _symbol_loop(exchange: ccxt_pro.Exchange, symbol: str):
    retry_delay = 5
    while True:
        started = time.monotonic()
        try:
            await _watch_and_signal_symbol(exchange, symbol)
        except asyncio.CancelledError:
            logger.info("Signal engine cancelled for %s", symbol)
            raise
        except Exception as e:
            if time.monotonic() - started > 600:
                retry_delay = 5
            logger.error("Signal engine error for %s, retrying in %ds: %s", symbol, retry_delay, e)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)


async def _fetch_htf(exchange: ccxt_pro.Exchange, symbol: str) -> Optional[pd.DataFrame]:
    try:
        raw = await exchange.fetch_ohlcv(symbol, HTF_TIMEFRAME, limit=HTF_CANDLES)
        if not raw or len(raw) < 50:
            return None
        df = pd.DataFrame(raw[:-1], columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        logger.warning("HTF fetch failed for %s: %s", symbol, e)
        return None


async def _watch_and_signal_symbol(exchange: ccxt_pro.Exchange, symbol: str):
    buffer = CandleBuffer()
    raw = await fetch_historical_ohlcv(exchange, symbol, TIMEFRAME)
    if not raw:
        raise RuntimeError(f"Could not seed candle buffer for {symbol}")

    buffer.seed(raw)
    forming = raw[-1]

    # 4h bias refreshes once per HTF candle — one REST call per 4 hours
    htf_df = await _fetch_htf(exchange, symbol)
    htf_fetched_at = time.monotonic()

    while True:
        ohlcv = await exchange.watch_ohlcv(symbol, TIMEFRAME)
        for candle in ohlcv:
            if candle[0] < forming[0]:
                continue
            if candle[0] == forming[0]:
                forming = candle
            else:
                # a new candle opened — the previous one is now closed
                buffer.append_closed(forming)
                if time.monotonic() - htf_fetched_at > HTF_REFRESH_SECONDS:
                    fresh = await _fetch_htf(exchange, symbol)
                    if fresh is not None:
                        htf_df = fresh
                    htf_fetched_at = time.monotonic()
                await process_closed_candle(symbol, forming, buffer, htf_df)
                forming = candle


async def start_signal_engine():
    return asyncio.create_task(watch_and_signal_loop())
