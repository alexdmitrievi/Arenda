"""Strategy runner tasks."""

import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger("tbx.workers.strategy_runner")


@celery_app.task(name="run_strategy_check")
def run_strategy_check(strategy_id: str):
    logger.info("run_strategy_check called: %s", strategy_id)
