"""Notification dispatch tasks."""

from app.workers.celery_app import celery_app


@celery_app.task(name="send_broadcast")
def send_broadcast(message: str, user_ids: list[str]):
    pass
