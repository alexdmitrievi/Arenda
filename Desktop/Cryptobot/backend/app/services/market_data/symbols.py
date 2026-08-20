"""Traded symbols and collection parameters — importable without ccxt."""

TRADE_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    "BNB/USDT", "ADA/USDT", "TRX/USDT", "TON/USDT", "LINK/USDT",
    "AVAX/USDT", "SUI/USDT", "AAVE/USDT", "ENA/USDT", "ONDO/USDT",
    "ZEC/USDT", "HYPE/USDT",
]
TIMEFRAME = "1h"
HTF_TIMEFRAME = "4h"
HTF_CANDLES = 200
HTF_REFRESH_SECONDS = 4 * 3600
LOOKBACK_CANDLES = 500
MAX_RETRY_DELAY = 300

# 5m trigger timeframe for entry refinement
TRIGGER_TIMEFRAME = "5m"
TRIGGER_CANDLES = 300
ARM_WINDOW_SECONDS = 6 * 3600  # a 1h signal must be confirmed on 5m within 6h


def passes_liquidity_filter(quote_volume_usd: float | None, threshold_usd: float) -> bool:
    """Liquidity gate: unknown volume fails closed — no data, no signal."""
    if quote_volume_usd is None:
        return False
    return quote_volume_usd >= threshold_usd
