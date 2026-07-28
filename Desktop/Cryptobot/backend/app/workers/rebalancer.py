"""Portfolio rebalancer tasks."""

from app.workers.celery_app import celery_app


@celery_app.task(name="rebalance_portfolios")
def rebalance_portfolios():
    pass
