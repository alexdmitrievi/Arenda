from __future__ import annotations

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

SUPPORTED_EXCHANGES = ["binance", "bybit", "okx"]


def _exchange_class(name: str):
    if not CCXT_AVAILABLE:
        raise RuntimeError("ccxt is not installed — exchange connectivity is unavailable")
    return getattr(ccxt_async, name)


async def create_exchange_client(
    exchange_name: str,
    api_key: str,
    secret: str,
    passphrase: str | None = None,
    testnet: bool = False,
) -> ccxt_async.Exchange:
    name = exchange_name.lower()
    if name not in SUPPORTED_EXCHANGES:
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

    exchange_class = _exchange_class(name)
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
    # Bybit spot uses triggerPrice for conditional market orders;
    # unified futures param kept for derivatives clients
    p["triggerPrice"] = stop_price
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
    p["triggerPrice"] = tp_price
    p["takeProfitPrice"] = tp_price
    return await exchange.create_order(symbol, "market", side, amount, None, p)


async def fetch_my_trades(
    exchange: ccxt_async.Exchange,
    symbol: str,
    since_ms: int | None = None,
    limit: int = 200,
) -> list[dict]:
    return await exchange.fetch_my_trades(symbol, since=since_ms, limit=limit)


async def find_order_by_client_id(
    exchange: ccxt_async.Exchange,
    client_order_id: str,
    symbol: str,
) -> dict | None:
    """Locate an order by its client id, checking open then closed orders.

    ccxt has no portable fetch-by-client-id API, so we scan both books and
    match on orderLinkId (Bybit) / clientOrderId (unified name).
    """
    for fetcher in (exchange.fetch_open_orders, exchange.fetch_closed_orders):
        try:
            orders = await fetcher(symbol)
        except Exception:
            continue
        for order in orders:
            info = order.get("info") or {}
            if info.get("orderLinkId") == client_order_id or \
               info.get("clientOrderId") == client_order_id:
                return order
    return None


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
