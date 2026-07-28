"""Market data collection tasks."""

import asyncio
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger("tbx.workers.market_data")


@celery_app.task(name="collect_ohlcv")
def collect_ohlcv(symbol: str, timeframe: str, exchange: str = "binance"):
    logger.info("collect_ohlcv called: %s %s %s", symbol, timeframe, exchange)


@celery_app.task(name="generate_signals")
def generate_signals():
    logger.info("generate_signals called")
