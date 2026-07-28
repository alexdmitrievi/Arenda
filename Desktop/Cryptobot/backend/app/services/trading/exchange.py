import logging
from typing import Any

try:
    import ccxt.async_support as ccxt_async
    CCXT_AVAILABLE = True
except ImportError:
    ccxt_async = None  # type: ignore
    CCXT_AVAILABLE = False

from app.core.security import decrypt_api_key

logger = logging.getLogger("tbx.trading.exchange")

EXCHANGE_MAP = {
    "binance": ccxt_async.binance,
    "bybit": ccxt_async.bybit,
    "okx": ccxt_async.okx,
}

SUPPORTED_EXCHANGES = list(EXCHANGE_MAP.keys())


async def create_exchange_client(
    exchange_name: str,
    api_key: str,
    secret: str,
    passphrase: str | None = None,
    testnet: bool = False,
) -> ccxt_async.Exchange:
    name = exchange_name.lower()
    if name not in EXCHANGE_MAP:
        raise ValueError(f"Unsupported exchange: {name}. Supported: {SUPPORTED_EXCHANGES}")

    config: dict[str, Any] = {
        "apiKey": decrypt_api_key(api_key),
        "secret": decrypt_api_key(secret),
        "enableRateLimit": True,
    }

    if passphrase:
        config["password"] = decrypt_api_key(passphrase)

    if testnet:
        config["testnet"] = True

    exchange_class = EXCHANGE_MAP[name]
    exchange = exchange_class(config)
    await exchange.load_markets()
    logger.info("Exchange %s connected: %d markets", name, len(exchange.markets))
    return exchange


async def fetch_ohlcv(
    exchange: ccxt_async.Exchange,
    symbol: str,
    timeframe: str = "4h",
    limit: int = 200,
) -> list[list[float]]:
    return await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)


async def fetch_ticker(
    exchange: ccxt_async.Exchange,
    symbol: str,
) -> dict:
    return await exchange.fetch_ticker(symbol)


async def create_market_order(
    exchange: ccxt_async.Exchange,
    symbol: str,
    side: str,
    amount: float,
    params: dict | None = None,
) -> dict:
    return await exchange.create_order(symbol, "market", side, amount, None, params or {})


async def create_limit_order(
    exchange: ccxt_async.Exchange,
    symbol: str,
    side: str,
    amount: float,
    price: float,
    params: dict | None = None,
) -> dict:
    return await exchange.create_order(symbol, "limit", side, amount, price, params or {})


async def create_stop_loss_order(
    exchange: ccxt_async.Exchange,
    symbol: str,
    side: str,
    amount: float,
    stop_price: float,
    params: dict | None = None,
) -> dict:
    p = params or {}
    p["stopLossPrice"] = stop_price
    return await exchange.create_order(symbol, "market", side, amount, None, p)


async def create_take_profit_order(
    exchange: ccxt_async.Exchange,
    symbol: str,
    side: str,
    amount: float,
    tp_price: float,
    params: dict | None = None,
) -> dict:
    p = params or {}
    p["takeProfitPrice"] = tp_price
    return await exchange.create_order(symbol, "market", side, amount, None, p)


async def cancel_order(
    exchange: ccxt_async.Exchange,
    order_id: str,
    symbol: str,
) -> dict:
    return await exchange.cancel_order(order_id, symbol)


async def cancel_all_orders(
    exchange: ccxt_async.Exchange,
    symbol: str | None = None,
) -> list[dict]:
    return await exchange.cancel_all_orders(symbol)


async def fetch_balance(exchange: ccxt_async.Exchange) -> dict:
    return await exchange.fetch_balance()


async def fetch_positions(
    exchange: ccxt_async.Exchange,
    symbols: list[str] | None = None,
) -> list[dict]:
    return await exchange.fetch_positions(symbols)


async def fetch_open_orders(
    exchange: ccxt_async.Exchange,
    symbol: str | None = None,
) -> list[dict]:
    return await exchange.fetch_open_orders(symbol)


async def close_exchange(exchange: ccxt_async.Exchange):
    await exchange.close()
    logger.info("Exchange connection closed")
