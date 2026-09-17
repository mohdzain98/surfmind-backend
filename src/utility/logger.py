"""Logging helpers for consistent console and file output.

Provides `AppLogger` (colored console + optional file handler, safe to
init once) and `DebugAwareLogger`, a `logging.Logger` subclass adding a
`.print()` method for rich, settings-gated pretty-printing of intermediate
data without scattering raw `print()` calls through the codebase.
"""

import json
import logging
from pathlib import Path

from rich.console import Console
from rich.pretty import pretty_repr

from src.utility.settings import settings

# ── existing color/formatter code stays unchanged ───────────────────────────

LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
}
RESET_COLOR = "\033[0m"

_STANDARD_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__)
_INTERNAL_FORMATTER_FIELDS = {"colored_levelname", "error_suffix", "extra_suffix"}


def _format_extra_value(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


class SafeExtraFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extra_items = []
        for key, value in sorted(record.__dict__.items()):
            if key in _STANDARD_LOG_RECORD_FIELDS or key in _INTERNAL_FORMATTER_FIELDS:
                continue
            if key.startswith("_"):
                continue
            extra_items.append(f"{key}={_format_extra_value(value)}")
        record.extra_suffix = f" | {' | '.join(extra_items)}" if extra_items else ""
        return super().format(record)


class ColorFormatter(SafeExtraFormatter):
    def format(self, record: logging.LogRecord) -> str:
        padded_level = f"{record.levelname + ':':<9}"
        color = LEVEL_COLORS.get(record.levelname, "")
        record.colored_levelname = (
            f"{color}{padded_level}{RESET_COLOR}" if color else padded_level
        )
        return super().format(record)


# ── NEW: debug pretty-printer ────────────────────────────────────────────────

_console = Console()


class DebugAwareLogger(logging.Logger):
    """Logger subclass adding `.print()` — a no-op unless `settings.print_enabled`
    (env var `PRINT`/`PRINT_ENABLED`) is true. Independent of the `level`
    passed to `AppLogger.init()`, which controls the stdlib log level —
    checked live off `settings.print_enabled` rather than cached at import
    time, so it reflects whatever's in the environment when the process
    actually starts.

    Lets agents/tools call `self.logger.print("Tool result", data)` everywhere,
    with rich output controlled by one setting instead of scattered `print()`
    calls that need manual removal later.
    """

    def print(
        self, label: str, data: object = None, *, raw_keys: set[str] | None = None
    ) -> None:
        """Pretty-print `data` under a `label` rule.

        `raw_keys` names dict keys whose string value should print as literal
        text (real newlines) instead of pretty_repr's escaped-string form —
        use it for long prompt text (e.g. raw_keys={"system", "user"}). Every
        other key, and any call without raw_keys, prints as a normal dict.
        """
        if not settings.print_enabled:
            return

        _console.rule(f"[bold cyan]{label}[/bold cyan]", style="cyan")
        if data is None:
            return

        if isinstance(data, dict) and raw_keys:
            remaining = {}
            for key, value in data.items():
                if key in raw_keys and isinstance(value, str):
                    _console.print(f"[bold]{key}:[/bold]")
                    _console.print(value)
                else:
                    remaining[key] = value
            if remaining:
                _console.print(pretty_repr(remaining))
            return

        _console.print(pretty_repr(data))


# Register BEFORE any getLogger() calls elsewhere in the app —
# AppLogger.init() below is the natural place to guarantee ordering.
logging.setLoggerClass(DebugAwareLogger)


class AppLogger:
    """Central logging helper."""

    _configured: bool = False

    @classmethod
    def init(
        cls,
        level: int = logging.INFO,
        log_to_file: bool = False,
        filename: str = "fastapi_server.log",
    ) -> None:
        """
        Initialize logging configuration.
        """

        if cls._configured:
            return
        cls._configured = True

        # setLoggerClass must run before any logger is created — already done
        # at module import above, this call is a safety no-op if init() runs first.
        logging.setLoggerClass(DebugAwareLogger)

        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_format = "%(colored_levelname)s %(name)s | %(message)s%(extra_suffix)s"
        console_handler.setFormatter(ColorFormatter(console_format))
        root_logger.addHandler(console_handler)

        for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uvicorn_logger = logging.getLogger(logger_name)
            uvicorn_logger.setLevel(level)
            uvicorn_logger.propagate = True

        if log_to_file:
            data_dir = Path(__file__).resolve().parents[2]
            logs_dir = data_dir / "data" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            file_path = logs_dir / filename

            file_handler = logging.FileHandler(file_path, encoding="utf-8")
            file_handler.setLevel(logging.WARNING)
            file_format = (
                "%(asctime)s | %(levelname)-8s | %(name)s | "
                "%(filename)s:%(lineno)d | %(message)s%(extra_suffix)s"
            )
            file_handler.setFormatter(
                SafeExtraFormatter(file_format, datefmt="%Y-%m-%d %H:%M:%S")
            )
            root_logger.addHandler(file_handler)

    @staticmethod
    def get_logger(name: str | None = None) -> "DebugAwareLogger":
        """
        Get a named logger.
        """

        logger_name = name if name is not None else __name__
        short_name = logger_name.split(".")[-1]
        return logging.getLogger(short_name)
