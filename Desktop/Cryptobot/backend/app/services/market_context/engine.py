"""Market Context Engine.

One place that answers: "should the trading robot be trading right now,
and how far along is the market cycle?"

Components (all price-derived or schedule-based — no scraping):
- BTC bias:      market structure (BOS) on BTC 4h and 1d — the "guide dog".
- Macro blackout: no new signals around scheduled high-impact US releases
                  (FOMC decisions, NFP; extendable via MACRO_EVENTS_JSON).
- Altseason:      breadth of top alts outperforming BTC over 90d, plus
                  ETH/BTC trend — a DIY replacement for BTC.D / OTHERS charts.
- Cycle clock:    months since the last halving → rough cycle phase.
- Risk assets:    S&P 500 / Russell 2000 vs their 50-day MA (Stooq CSV,
                  best-effort; the engine degrades gracefully without it).

The scheduler refreshes the context every 30 minutes into Redis; the signal
engine reads it before publishing a signal.
"""

import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import pandas as pd

from app.core.redis import get_redis

logger = logging.getLogger("tbx.market_context")

CONTEXT_REDIS_KEY = "market:context"
CONTEXT_TTL = 3600 * 2

MACRO_BLACKOUT_BEFORE_MIN = 60
MACRO_BLACKOUT_AFTER_MIN = 60

# FOMC rate decisions, second day, statement at 19:00 UTC (14:00 ET).
# Published a year ahead by the Fed; extend/override via MACRO_EVENTS_JSON env.
FOMC_2026_UTC = [
    "2026-01-28T19:00:00+00:00",
    "2026-03-18T19:00:00+00:00",
    "2026-04-29T19:00:00+00:00",
    "2026-06-17T19:00:00+00:00",
    "2026-07-29T19:00:00+00:00",
    "2026-09-16T19:00:00+00:00",
    "2026-10-28T19:00:00+00:00",
    "2026-12-09T19:00:00+00:00",
]

LAST_HALVING = datetime(2024, 4, 20, tzinfo=timezone.utc)

# alt basket for the altseason breadth metric (BTC excluded by definition)
ALT_BASKET = [
    "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "BNB/USDT",
    "ADA/USDT", "TRX/USDT", "TON/USDT", "LINK/USDT", "AVAX/USDT",
]

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"


def _nfp_dates(months_ahead: int = 12) -> list[datetime]:
    """Non-farm payrolls: first Friday of each month, 13:30 UTC (8:30 ET)."""
    dates = []
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    for _ in range(months_ahead):
        d = datetime(year, month, 1, 13, 30, tzinfo=timezone.utc)
        while d.weekday() != 4:  # Friday
            d += timedelta(days=1)
        dates.append(d)
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return dates


def scheduled_macro_events(extra_events_json: str = "") -> list[dict]:
    events = [{"name": "FOMC rate decision", "at": ts} for ts in FOMC_2026_UTC]
    events += [{"name": "US Non-Farm Payrolls", "at": d.isoformat()} for d in _nfp_dates()]
    if extra_events_json:
        try:
            for e in json.loads(extra_events_json):
                events.append({"name": str(e.get("name", "event")), "at": str(e["at"])})
        except Exception as e:
            logger.warning("Bad MACRO_EVENTS_JSON: %s", e)
    return sorted(events, key=lambda e: e["at"])


def macro_blackout(now: Optional[datetime] = None, extra_events_json: str = "") -> dict:
    """Is `now` inside the no-trade window around a scheduled release?"""
    now = now or datetime.now(timezone.utc)
    for event in scheduled_macro_events(extra_events_json):
        at = datetime.fromisoformat(event["at"])
        start = at - timedelta(minutes=MACRO_BLACKOUT_BEFORE_MIN)
        end = at + timedelta(minutes=MACRO_BLACKOUT_AFTER_MIN)
        if start <= now <= end:
            return {"active": True, "event": event["name"], "until": end.isoformat()}
        if at > now + timedelta(hours=24):
            break
    return {"active": False, "event": None, "until": None}


def _trend_from_ohlcv(raw: list[list]) -> str:
    from app.services.strategies.smc import SignalGenerator, StructuralAnalysis

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if len(df) < 50:
        return "NEUTRAL"
    swings = StructuralAnalysis.detect_swing_points(df)
    bos = StructuralAnalysis.detect_bos(df, swings)
    return SignalGenerator()._determine_trend(bos)


async def btc_bias(exchange) -> dict:
    """The guide dog: BTC structure on 4h and 1d decides whether longs run.

    RISK_OFF  — bearish structure on BOTH 4h and 1d: long signals suppressed.
    CAUTION   — bearish on one of the two: longs allowed, confidence penalty.
    RISK_ON   — everything else.
    """
    h4 = _trend_from_ohlcv(await exchange.fetch_ohlcv("BTC/USDT", "4h", limit=300))
    d1 = _trend_from_ohlcv(await exchange.fetch_ohlcv("BTC/USDT", "1d", limit=300))

    if h4 == "BEARISH" and d1 == "BEARISH":
        mode = "RISK_OFF"
    elif "BEARISH" in (h4, d1):
        mode = "CAUTION"
    else:
        mode = "RISK_ON"
    return {"h4": h4, "d1": d1, "mode": mode}


async def altseason_score(exchange) -> dict:
    """0-100: how many top alts beat BTC over the last 90 days, plus ETH/BTC trend.

    >=75 — altseason in force (classic breadth threshold), <=25 — BTC season.
    """
    try:
        btc_raw = await exchange.fetch_ohlcv("BTC/USDT", "1d", limit=95)
        btc_ret = btc_raw[-1][4] / btc_raw[-90][4] - 1 if len(btc_raw) >= 90 else None
        if btc_ret is None:
            return {"score": None, "breadth_pct": None, "ethbtc_trend": "NEUTRAL"}

        outperformers = 0
        counted = 0
        for symbol in ALT_BASKET:
            try:
                raw = await exchange.fetch_ohlcv(symbol, "1d", limit=95)
                if len(raw) >= 90:
                    alt_ret = raw[-1][4] / raw[-90][4] - 1
                    counted += 1
                    if alt_ret > btc_ret:
                        outperformers += 1
            except Exception:
                continue

        breadth = round(outperformers / counted * 100, 1) if counted else None

        ethbtc_raw = await exchange.fetch_ohlcv("ETH/BTC", "1d", limit=60)
        ethbtc = pd.Series([c[4] for c in ethbtc_raw])
        ma50 = ethbtc.rolling(50).mean()
        ethbtc_trend = "NEUTRAL"
        if len(ethbtc) >= 50 and not pd.isna(ma50.iloc[-1]):
            ethbtc_trend = "UP" if ethbtc.iloc[-1] > ma50.iloc[-1] else "DOWN"

        score = breadth
        if score is not None:
            if ethbtc_trend == "UP":
                score = min(100.0, score + 10)
            elif ethbtc_trend == "DOWN":
                score = max(0.0, score - 10)

        return {"score": score, "breadth_pct": breadth, "ethbtc_trend": ethbtc_trend}
    except Exception as e:
        logger.warning("Altseason score failed: %s", e)
        return {"score": None, "breadth_pct": None, "ethbtc_trend": "NEUTRAL"}


def cycle_clock(now: Optional[datetime] = None) -> dict:
    """Rough halving-cycle phase. A coarse map, not a timing tool."""
    now = now or datetime.now(timezone.utc)
    months = (now - LAST_HALVING).days / 30.44
    if months < 6:
        phase = "post_halving_accumulation"
    elif months < 18:
        phase = "bull_expansion"
    elif months < 30:
        phase = "late_cycle_distribution"
    elif months < 42:
        phase = "bear_contraction"
    else:
        phase = "pre_halving_accumulation"
    return {"months_since_halving": round(months, 1), "phase": phase}


async def _stooq_above_ma50(symbol: str) -> Optional[bool]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(STOOQ_URL.format(symbol=symbol))
        if resp.status_code != 200 or not resp.text.startswith("Date"):
            return None
        df = pd.read_csv(io.StringIO(resp.text))
        closes = df["Close"].astype(float)
        if len(closes) < 60:
            return None
        return bool(closes.iloc[-1] > closes.rolling(50).mean().iloc[-1])
    except Exception:
        return None


async def risk_assets() -> dict:
    """Equity risk appetite: SPX and Russell 2000 vs their 50-day MA."""
    spx = await _stooq_above_ma50("^spx")
    rut = await _stooq_above_ma50("^rut")
    if spx is None and rut is None:
        mode = "UNKNOWN"
    elif spx is False and rut is False:
        mode = "RISK_OFF"
    elif spx and rut:
        mode = "RISK_ON"
    else:
        mode = "MIXED"
    return {"spx_above_ma50": spx, "rut_above_ma50": rut, "mode": mode}


async def compute_context(exchange, extra_events_json: str = "") -> dict[str, Any]:
    context = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "btc": await btc_bias(exchange),
        "altseason": await altseason_score(exchange),
        "cycle": cycle_clock(),
        "equities": await risk_assets(),
        "macro_blackout": macro_blackout(extra_events_json=extra_events_json),
    }
    return context


async def store_context(context: dict) -> None:
    redis = await get_redis()
    await redis.set(CONTEXT_REDIS_KEY, json.dumps(context, default=str), ex=CONTEXT_TTL)


async def load_context() -> Optional[dict]:
    try:
        redis = await get_redis()
        data = await redis.get(CONTEXT_REDIS_KEY)
        return json.loads(data) if data else None
    except Exception:
        return None
