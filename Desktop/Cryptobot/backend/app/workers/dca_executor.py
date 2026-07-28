"""DCA executor tasks."""

from app.workers.celery_app import celery_app


@celery_app.task(name="execute_dca_plans")
def execute_dca_plans():
    pass
