"""Celery application for async jobs (emails, webhooks reprocessing, retention). Requires REDIS_URL.
Pending: workers are not running in the preview environment; operations currently execute inline."""
import os

from celery import Celery

celery_app = Celery("leamse", broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"))
celery_app.conf.task_default_queue = "default"
