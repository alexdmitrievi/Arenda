"""Bybit client factory and USDT-M perpetual helpers.

All exchange-facing code (execution, position sync, reconciliation, kill
switch, key-permission checks) must build clients through here so that the
testnet switch and margin/leverage policy stay in one place.
"""

import logging

from app.config import settings

logger = logging.getLogger("tbx.trading.bybit")


def make_client(api_key: str, secret: str, passphrase: str | None = None):
    """ccxt bybit client honoring BYBIT_TESTNET / leverage / margin mode."""
    import ccxt.async_support as ccxt_async

    config: dict = {
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
    }
    if passphrase:
        config["password"] = passphrase
    if settings.BYBIT_TESTNET:
        config["testnet"] = True
    return ccxt_async.bybit(config)


def perp_symbol(symbol: str) -> str:
    """Spot-style 'BTC/USDT' → ccxt linear-perp 'BTC/USDT:USDT'."""
    if ":" in symbol:
        return symbol
    return f"{symbol}:USDT"


async def prepare_symbol(exchange, symbol: str) -> None:
    """Apply the platform leverage/margin policy before any order."""
    margin_mode = settings.BYBIT_MARGIN_MODE
    leverage = int(settings.BYBIT_LEVERAGE)
    try:
        await exchange.set_margin_mode(margin_mode, symbol)
    except Exception as e:
        logger.warning("set_margin_mode failed for %s (%s): %s", symbol, margin_mode, e)
    try:
        await exchange.set_leverage(leverage, symbol)
    except Exception as e:
        logger.error("set_leverage failed for %s: %s", symbol, e)
        raise
    logger.info("Prepared %s: margin=%s leverage=%dx", symbol, margin_mode, leverage)
