"""DeepSeek analyst (Variant A).

The signal engine stays deterministic: entries, stops and targets come from
the rule-based SMC logic. DeepSeek only writes a human-readable explanation
of the setup from the same data the rules consumed — never proposes levels.
Fails open: on any API error the signal is published without commentary.
"""

import logging

import pandas as pd

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger("tbx.ai.analyst")

_CANDLE_LIMIT = 30
_MAX_TOKENS = 700
_TIMEOUT_SECONDS = 30


def _candles_block(df: pd.DataFrame, limit: int = _CANDLE_LIMIT) -> str:
    if df is None or df.empty:
        return "(нет данных)"
    tail = df.tail(limit)
    lines = []
    for _, row in tail.iterrows():
        lines.append(
            f"{row['open']:.6g},{row['high']:.6g},{row['low']:.6g},"
            f"{row['close']:.6g},{row['volume']:.6g}"
        )
    return "\n".join(lines)


def _build_prompt(
    symbol: str,
    direction: str,
    entry: float,
    stop: float,
    tps: list[float],
    confidence: int,
    metadata: dict,
    df1h: pd.DataFrame | None,
    df5m: pd.DataFrame | None,
) -> str:
    reasons = metadata.get("reasons") or []
    regime = metadata.get("regime") or {}
    market_context = metadata.get("market_context") or {}
    fib_ote = metadata.get("fib_ote") or {}
    return (
        "Ты — трейдинг-аналитик (Smart Money Concepts). Ниже — данные "
        "детерминированного сигнального движка по инструменту "
        f"{symbol}, направление {direction}. "
        "Твоя задача — ТОЛЬКО пояснить сетап человеческим языком, опираясь "
        "исключительно на предоставленные данные. Не придумывай фактов, "
        "не выдумывай уровни, не давай рекомендаций покупать/продавать.\n\n"
        f"Вход: {entry}\nСтоп-лосс: {stop}\n"
        f"Цели: {', '.join(f'{t:g}' for t in tps) if tps else '—'}\n"
        f"Уверенность движка: {confidence}/100\n"
        f"Режим рынка: {regime.get('regime', '?')} "
        f"(slope_atr={regime.get('slope_atr', '?')})\n"
        f"Тренд HTF: {metadata.get('htf_trend', '?')}\n"
        f"OTE-зона фибо: {fib_ote}\n"
        f"Контекст: BTC={market_context.get('btc_mode', '?')}, "
        f"altseason={market_context.get('altseason', '?')}\n"
        f"Факторы движка: {'; '.join(reasons) if reasons else '—'}\n\n"
        "Свечи 1H (open,high,low,close,volume), последние 30:\n"
        f"{_candles_block(df1h)}\n\n"
        "Свечи 5m (тот же формат), последние 30:\n"
        f"{_candles_block(df5m)}\n\n"
        "Формат ответа (максимум 200 слов, по-русски):\n"
        "1) Формация: что видно по структуре.\n"
        "2) Сильные стороны сетапа.\n"
        "3) Слабые места / риски.\n"
        "4) Ключевые уровни для наблюдения."
    )


async def analyze_signal(
    symbol: str,
    direction: str,
    entry: float,
    stop: float,
    tps: list[float],
    confidence: int,
    metadata: dict,
    df1h: pd.DataFrame | None = None,
    df5m: pd.DataFrame | None = None,
) -> str:
    """Return the analyst commentary, or '' when the AI is unavailable."""
    if not settings.DEEPSEEK_API_KEY:
        return ""
    try:
        client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=_TIMEOUT_SECONDS,
            max_retries=1,
        )
        prompt = _build_prompt(
            symbol, direction, entry, stop, tps, confidence, metadata, df1h, df5m
        )
        response = await client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=_MAX_TOKENS,
        )
        text = (response.choices[0].message.content or "").strip()
        logger.info("AI analysis for %s %s: %d chars", symbol, direction, len(text))
        return text
    except Exception as e:
        logger.warning("AI analysis failed for %s: %s", symbol, e)
        return ""
