"""Notification dispatch tasks."""

import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger("tbx.workers.notifications")


@celery_app.task(name="send_broadcast")
def send_broadcast(message: str, user_ids: list[str]):
    logger.info("send_broadcast called: %s to %d users", message[:50], len(user_ids))


@celery_app.task(name="notify_signal")
def notify_signal(signal_id: str):
    logger.info("notify_signal called: %s", signal_id)
