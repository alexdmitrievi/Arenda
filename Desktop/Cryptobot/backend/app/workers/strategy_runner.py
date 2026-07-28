"""Strategy runner tasks."""

from app.workers.celery_app import celery_app


@celery_app.task(name="run_strategy_check")
def run_strategy_check(strategy_id: str):
    pass
