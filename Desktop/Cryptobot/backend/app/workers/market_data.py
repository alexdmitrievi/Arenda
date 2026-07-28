"""Market data collection tasks."""

from app.workers.celery_app import celery_app


@celery_app.task(name="collect_ohlcv")
def collect_ohlcv(symbol: str, timeframe: str, exchange: str = "binance"):
    pass
