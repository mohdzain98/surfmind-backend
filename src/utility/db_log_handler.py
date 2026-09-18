"""Persists WARNING+ log records to Postgres, off the request path.

Logger calls happen from sync code, async code, and even outside any event
loop (app startup) — a synchronous `psycopg2` connection on its own
background thread (stdlib `QueueListener`) sidesteps the cross-event-loop
pitfall the app's async engine would otherwise hit here (see the Celery +
`asyncio.run()` lesson from `sync_service`). `emit()` on the request-facing
side only ever does a non-blocking queue put.
"""

import json
import logging
import logging.handlers
import queue
from typing import Optional

import psycopg2

from src.utility.settings import settings

_STANDARD_FIELDS = set(logging.makeLogRecord({}).__dict__)
_INTERNAL_FIELDS = {"colored_levelname", "error_suffix", "extra_suffix"}
# Other handlers on the same root logger format this exact record object
# in place (not a copy) before this handler ever sees it — e.g. the file
# handler's formatter sets `.message`/`.asctime` as a side effect of
# `Formatter.format()`. Excluded explicitly since which handler runs first
# isn't something this module controls.
_FORMATTER_SIDE_EFFECT_FIELDS = {"message", "asctime"}

_log_queue: "queue.Queue" = queue.Queue(maxsize=10000)
_listener: Optional[logging.handlers.QueueListener] = None


def _extract_extra(record: logging.LogRecord) -> dict:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_FIELDS
        and key not in _INTERNAL_FIELDS
        and key not in _FORMATTER_SIDE_EFFECT_FIELDS
        and not key.startswith("_")
    }


def _sync_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


class _DBWriteHandler(logging.Handler):
    """Only ever runs on the `QueueListener`'s background thread."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            extra = _extract_extra(record)
            conn = psycopg2.connect(_sync_dsn())
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO app_logs (level, logger_name, message, extra) "
                        "VALUES (%s, %s, %s, %s)",
                        (
                            record.levelname,
                            record.name,
                            record.getMessage(),
                            json.dumps(extra, default=str) if extra else None,
                        ),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            # A logging-to-DB failure must never crash the app or recurse
            # back into logging (which would just fail the same way again).
            pass


class _RawQueueHandler(logging.handlers.QueueHandler):
    """Skips `QueueHandler`'s default `prepare()`.

    The stdlib default calls `self.format(record)` and flattens the record
    to a plain string — meant for multiprocessing-safe queues. This queue
    never leaves the process, and flattening early would bake stray
    `message`/`asctime` attributes onto the record before `_extract_extra`
    sees it, leaking them into the `extra` JSONB column as noise.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record


def get_queue_handler() -> logging.handlers.QueueHandler:
    """The handler attached to the root logger — enqueue-only, never blocks."""
    return _RawQueueHandler(_log_queue)


def start_listener() -> None:
    """Start the background thread that drains the queue into Postgres."""
    global _listener
    if _listener is not None:
        return
    _listener = logging.handlers.QueueListener(
        _log_queue, _DBWriteHandler(), respect_handler_level=False
    )
    _listener.start()


def stop_listener() -> None:
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None
