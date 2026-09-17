"""Celery app for background page classification.

Reuses the existing Redis instance as both broker and result backend — no
new infra beyond the worker process itself. Purely trigger-based (see
`category_controller`'s classify endpoint); no Celery Beat/scheduled tasks.
"""

from celery import Celery

from src.utility.settings import settings

_redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/0"

celery_app = Celery("surfmind", broker=_redis_url, backend=_redis_url)
celery_app.autodiscover_tasks(["src.services.classification_service"])
