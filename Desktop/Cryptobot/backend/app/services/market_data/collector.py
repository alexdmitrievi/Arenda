from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.models.trade import Signal, Strategy, StrategyType
from app.services.market_data.symbols import (
    HTF_CANDLES,
    HTF_REFRESH_SECONDS,
    HTF_TIMEFRAME,
    LOOKBACK_CANDLES,
    MAX_RETRY_DELAY,
    TIMEFRAME,
    TRADE_SYMBOLS,
)
from app.services.strategies.smc import SMCStrategy
from app.services.trading.market_data import cache_ohlcv, set_latest_price

try:
    import ccxt.pro as ccxt_pro
    CCXT_PRO_AVAILABLE = True
except ImportError:
    ccxt_pro = None  # type: ignore
    CCXT_PRO_AVAILABLE = False

logger = logging.getLogger("tbx.market_data.collector")

_smc_strategy: Optional[SMCStrategy] = None


def get_smc_strategy() -> SMCStrategy:
    global _smc_strategy
    if _smc_strategy is None:
        # RR mandate: market structure must offer at least 2:1 reward-to-risk
        # to the first target (owner decision 2026-08-20); the TP ladder stays 3R/5R/7R
        _smc_strategy = SMCStrategy(min_rr_ratio=2.0, min_confidence=50)
    return _smc_strategy


async def _validate_symbols(exchange: ccxt_pro.Exchange) -> list[str]:
    """Not every configured pair is guaranteed to be listed on the exchange —
    skip missing ones loudly instead of retry-looping on them forever."""
    await exchange.load_markets()
    valid = [s for s in TRADE_SYMBOLS if s in exchange.markets]
    missing = [s for s in TRADE_SYMBOLS if s not in exchange.markets]
    if missing:
        logger.warning("Symbols not listed on %s, skipped: %s", exchange.id, ", ".join(missing))
    return valid


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


async def fetch_historical_ohlcv(exchange: ccxt_pro.Exchange, symbol: str,
                                 timeframe: str = TIMEFRAME) -> list[list]:
    try:
        raw = await exchange.fetch_ohlcv(symbol, timeframe, limit=LOOKBACK_CANDLES)
        if not raw or len(raw) < 50:
            logger.warning("Insufficient OHLCV data for %s %s: %d candles",
                           symbol, timeframe, len(raw) if raw else 0)
            return []
        return raw
    except Exception as e:
        logger.error("Failed to fetch OHLCV for %s %s: %s", symbol, timeframe, e)
        return []


async def build_signal_candidate(symbol: str, df: pd.DataFrame,
                                 htf_df: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """Run the engine and every gate; return a candidate dict or None.

    The candidate is NOT stored yet — it waits for the 5m confirmation.
    """
    from app.services.market_context.engine import load_context, macro_blackout
    from app.services.trading.killswitch import is_trading_halted
    from app.services.trading.market_data import get_quote_volume
    from app.services.market_data.symbols import passes_liquidity_filter

    # operator kill switch: no new signals while trading is halted
    if await is_trading_halted():
        logger.info("Signal suppressed for %s: trading halted by kill switch", symbol)
        return None

    # macro blackout is schedule-based and cheap — always computed fresh
    blackout = macro_blackout(extra_events_json=settings.MACRO_EVENTS_JSON)
    if blackout["active"]:
        logger.info("Signal suppressed for %s: macro blackout (%s until %s)",
                    symbol, blackout["event"], blackout["until"])
        return None

    # liquidity gate: >= $300M 24h quote volume on Binance (owner decision)
    redis = await get_redis()
    quote_volume = await get_quote_volume(redis, symbol)
    if not passes_liquidity_filter(quote_volume, settings.MIN_DAILY_VOLUME_USD):
        logger.info(
            "Signal suppressed for %s: 24h volume %.0f < %d USD (liquidity gate)",
            symbol, quote_volume or 0, settings.MIN_DAILY_VOLUME_USD,
        )
        return None

    strategy_engine = get_smc_strategy()
    signal_result = strategy_engine.generate_signal(df, symbol, htf_df=htf_df)

    if signal_result.direction == "NONE" or signal_result.confidence < 50:
        return None

    # BTC is the guide dog: while it holds bearish structure on 4h AND 1d,
    # long signals across the board are suppressed; one bearish TF costs
    # a confidence penalty instead of a hard veto
    context = await load_context()
    if context and signal_result.direction == "BUY":
        btc_mode = context.get("btc", {}).get("mode")
        if btc_mode == "RISK_OFF":
            logger.info("BUY signal suppressed for %s: BTC bearish on 4h+1d", symbol)
            return None
        if btc_mode == "CAUTION":
            signal_result.confidence = max(0, signal_result.confidence - 10)
            signal_result.metadata.setdefault("reasons", []).append(
                "BTC частично медвежий (4h или 1d) — штраф к уверенности"
            )
            if signal_result.confidence < 50:
                return None
    if context:
        signal_result.metadata["market_context"] = {
            "btc_mode": context.get("btc", {}).get("mode"),
            "altseason": context.get("altseason", {}).get("score"),
            "cycle_phase": context.get("cycle", {}).get("phase"),
        }

    return {
        "symbol": symbol,
        "direction": signal_result.direction,
        "entry": float(signal_result.entry),
        "stop_loss": float(signal_result.stop_loss),
        "take_profit": list(signal_result.take_profit),
        "confidence": signal_result.confidence,
        "metadata": signal_result.metadata,
        "df1h": df.tail(40).copy(),
    }


async def store_candidate(candidate: dict, df5m: Optional[pd.DataFrame] = None) -> Optional[Signal]:
    """Persist a confirmed candidate, attach the AI commentary, notify."""
    from app.services.ai.analyst import analyze_signal

    symbol = candidate["symbol"]
    direction = candidate["direction"]
    direction_map = {"BUY": "buy", "SELL": "sell"}

    async with async_session_factory() as db:
        try:
            strategy = await _get_or_create_smc_strategy(db)
            signal = Signal(
                strategy_id=strategy.id,
                symbol=symbol,
                direction=direction_map.get(direction, "buy"),
                entry=Decimal(str(round(candidate["entry"], 8))),
                stop_loss=Decimal(str(round(candidate["stop_loss"], 8))),
                take_profit=[round(tp, 8) for tp in candidate["take_profit"]],
                confidence=candidate["confidence"],
                metadata_=candidate["metadata"],
            )
            db.add(signal)
            await db.commit()
            await db.refresh(signal)
        except Exception as e:
            await db.rollback()
            logger.error("Failed to store signal for %s: %s", symbol, e)
            return None

    # Variant A: DeepSeek explains the setup, never proposes levels
    analysis = await analyze_signal(
        symbol=symbol,
        direction=direction,
        entry=candidate["entry"],
        stop=candidate["stop_loss"],
        tps=candidate["take_profit"],
        confidence=candidate["confidence"],
        metadata=candidate["metadata"],
        df1h=candidate.get("df1h"),
        df5m=df5m,
    )
    if analysis:
        async with async_session_factory() as db:
            row = await db.get(Signal, signal.id)
            if row is not None:
                meta = dict(row.metadata_ or {})
                meta["ai_analysis"] = analysis
                row.metadata_ = meta
                await db.commit()
        signal.metadata_ = dict(signal.metadata_ or {})
        signal.metadata_["ai_analysis"] = analysis

    await notify_signal(signal)
    logger.info(
        "Signal stored: %s %s conf=%d entry=%.4f sl=%.4f",
        symbol, direction, candidate["confidence"],
        candidate["entry"], candidate["stop_loss"],
    )
    return signal


async def process_closed_candle(symbol: str, candle: list, buffer: CandleBuffer,
                                htf_df: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """On a closed 1h candle: cache data and build a signal candidate.

    Returns the candidate dict (NOT stored — it awaits 5m confirmation).
    """
    try:
        redis = await get_redis()
        await cache_ohlcv(redis, symbol, TIMEFRAME, list(buffer.candles)[-100:])
        await set_latest_price(redis, symbol, float(candle[4]))
    except Exception as e:
        logger.error("Failed to cache candle for %s: %s", symbol, e)

    if len(buffer) < 50:
        return None

    try:
        return await build_signal_candidate(symbol, buffer.to_dataframe(), htf_df)
    except Exception as e:
        logger.error("Signal generation failed for %s: %s", symbol, e)
        return None


async def _confirm_and_store(symbol: str, m5_buffer: CandleBuffer, state: dict) -> None:
    """Check an armed 1h candidate against the 5m chart; store when confirmed."""
    from app.services.market_data.m5_trigger import (
        find_5m_confirmation,
        refine_entry_5m,
        refined_rr,
    )
    from app.services.market_data.symbols import ARM_WINDOW_SECONDS

    armed = state.get("armed")
    if not armed:
        return

    if time.time() - state["armed_at"] > ARM_WINDOW_SECONDS:
        state["armed"] = None
        logger.info("5m confirmation window expired for %s — signal dropped", symbol)
        return

    df5m = m5_buffer.to_dataframe()
    if not find_5m_confirmation(df5m, armed["direction"]):
        return

    refined = refine_entry_5m(
        df5m, armed["direction"], armed["entry"], armed["stop_loss"]
    )
    tp1 = armed["take_profit"][0] if armed["take_profit"] else None
    rr = refined_rr(refined, armed["stop_loss"], tp1, armed["direction"]) if tp1 else None
    if rr is None or rr < 2.0:
        state["armed"] = None
        logger.info(
            "5m confirmed for %s but refined entry RR=%.2f < 2 — signal dropped",
            symbol, rr or 0.0,
        )
        return

    armed["entry"] = refined
    armed["metadata"].setdefault("reasons", []).append(
        f"Вход уточнён по 5m-структуре (RR {rr}:1)"
    )
    await store_candidate(armed, df5m=df5m)
    state["armed"] = None
    logger.info("5m confirmation stored signal for %s at %.4f", symbol, refined)


async def notify_signal(signal: Signal):
    try:
        from app.services.trading.execution import stop_zone_and_rr

        redis = await get_redis()
        zone_pct, rr = stop_zone_and_rr(
            float(signal.entry), float(signal.stop_loss),
            float(signal.take_profit[0]) if signal.take_profit else None,
        )
        payload = {
            "id": str(signal.id),
            "symbol": signal.symbol,
            "direction": signal.direction.value if hasattr(signal.direction, 'value') else str(signal.direction),
            "entry": float(signal.entry),
            "stop_loss": float(signal.stop_loss),
            "take_profit": signal.take_profit if isinstance(signal.take_profit, list) else [],
            "confidence": signal.confidence,
            "stop_zone_pct": zone_pct,
            "rr": rr,
            "analysis": (signal.metadata_ or {}).get("ai_analysis", ""),
            "created_at": signal.created_at.isoformat() if signal.created_at else datetime.now(timezone.utc).isoformat(),
        }
        await redis.publish("signals:new", json.dumps(payload, default=str))
        logger.info("Signal notification published: %s %s", signal.symbol, signal.direction)
    except Exception as e:
        logger.error("Failed to notify signal: %s", e)


async def watch_tickers_loop():
    """Keeps latest prices in Redis for the UI and paper trading."""
    exchange = ccxt_pro.binance({"enableRateLimit": True})
    symbols = await _validate_symbols(exchange)
    logger.info("Ticker collector started for %d symbols", len(symbols))

    retry_delay = 5
    try:
        while True:
            started = time.monotonic()
            try:
                await _watch_tickers(exchange, symbols)
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


async def _watch_tickers(exchange: ccxt_pro.Exchange, symbols: list[str]):
    from app.services.trading.market_data import set_quote_volume

    while True:
        tickers = await exchange.watch_tickers(symbols)
        redis = await get_redis()
        for symbol, ticker in tickers.items():
            if ticker and ticker.get("last"):
                try:
                    await set_latest_price(redis, symbol, float(ticker["last"]))
                except Exception:
                    pass
                try:
                    quote_volume = ticker.get("quoteVolume")
                    if quote_volume is not None:
                        await set_quote_volume(redis, symbol, float(quote_volume))
                except Exception:
                    pass


async def start_collector():
    return asyncio.create_task(watch_tickers_loop())


async def watch_and_signal_loop():
    exchange = ccxt_pro.binance({"enableRateLimit": True})
    symbols = await _validate_symbols(exchange)
    logger.info("Signal Engine started. Symbols: %s", ", ".join(symbols))
    try:
        await asyncio.gather(*(_symbol_loop(exchange, s) for s in symbols))
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
    from app.services.market_data.symbols import TRIGGER_CANDLES, TRIGGER_TIMEFRAME

    buffer = CandleBuffer()
    raw = await fetch_historical_ohlcv(exchange, symbol, TIMEFRAME)
    if not raw:
        raise RuntimeError(f"Could not seed candle buffer for {symbol}")

    buffer.seed(raw)
    forming = raw[-1]

    # 5m trigger buffer for entry refinement
    m5_buffer = CandleBuffer(maxlen=TRIGGER_CANDLES)
    m5_raw = await fetch_historical_ohlcv(exchange, symbol, TRIGGER_TIMEFRAME)
    m5_forming = None
    if m5_raw:
        m5_buffer.seed(m5_raw)
        m5_forming = m5_raw[-1]

    # 4h bias refreshes once per HTF candle — one REST call per 4 hours
    htf_df = await _fetch_htf(exchange, symbol)
    htf_fetched_at = time.monotonic()

    state: dict = {"armed": None, "armed_at": 0.0}

    async def watch_1h() -> None:
        nonlocal forming, htf_df, htf_fetched_at
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
                    candidate = await process_closed_candle(
                        symbol, forming, buffer, htf_df
                    )
                    if candidate:
                        state["armed"] = candidate
                        state["armed_at"] = time.time()
                        logger.info(
                            "1h signal armed for %s (%s) — awaiting 5m confirmation",
                            symbol, candidate["direction"],
                        )
                    forming = candle

    async def watch_5m() -> None:
        nonlocal m5_forming
        while True:
            candles = await exchange.watch_ohlcv(symbol, TRIGGER_TIMEFRAME)
            for candle in candles:
                if m5_forming is None or candle[0] < m5_forming[0]:
                    continue
                if candle[0] == m5_forming[0]:
                    m5_forming = candle
                else:
                    m5_buffer.append_closed(m5_forming)
                    m5_forming = candle
                    await _confirm_and_store(symbol, m5_buffer, state)

    await asyncio.gather(watch_1h(), watch_5m())


async def start_signal_engine():
    return asyncio.create_task(watch_and_signal_loop())
