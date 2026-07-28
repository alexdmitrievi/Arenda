"""Celery application for background tasks."""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "tbx_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.market_data",
        "app.workers.strategy_runner",
        "app.workers.dca_executor",
        "app.workers.rebalancer",
        "app.workers.notifications",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Moscow",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,
    task_soft_time_limit=25 * 60,
)
