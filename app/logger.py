"""
Logging configuration for the School Contact Discovery System.

Creates four separate log channels:
  - crawl:      General crawl events (INFO+)
  - error:      Error-level events only
  - retry:      Retry attempts
  - statistics: Structured JSON statistics snapshots

All file handlers use RotatingFileHandler.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

from rich.logging import RichHandler

_CONFIGURED = False


def setup_logging(
    log_dir: str = "logs",
    level: str = "INFO",
    console_level: str = "INFO",
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
) -> None:
    """
    Configure all log channels for the application.

    Args:
        log_dir: Directory where log files are written.
        level: File log level (DEBUG/INFO/WARNING/ERROR/CRITICAL).
        console_level: Console log level.
        max_bytes: Max size of each log file before rotation.
        backup_count: Number of rotated log files to keep.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    file_level = getattr(logging, level.upper(), logging.INFO)
    con_level = getattr(logging, console_level.upper(), logging.INFO)

    fmt_file = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    def _rotating(filename: str, level_override: Optional[int] = None) -> logging.Handler:
        h = logging.handlers.RotatingFileHandler(
            log_path / filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        h.setFormatter(fmt_file)
        h.setLevel(level_override or file_level)
        return h

    # ------------------------------------------------------------------
    # crawl logger  (INFO+)
    # ------------------------------------------------------------------
    crawl_logger = logging.getLogger("crawl")
    crawl_logger.setLevel(logging.DEBUG)
    crawl_logger.addHandler(_rotating("crawl.log"))

    # ------------------------------------------------------------------
    # error logger  (ERROR+)
    # ------------------------------------------------------------------
    error_logger = logging.getLogger("error")
    error_logger.setLevel(logging.ERROR)
    error_logger.addHandler(_rotating("error.log", logging.ERROR))

    # ------------------------------------------------------------------
    # retry logger  (WARNING+)
    # ------------------------------------------------------------------
    retry_logger = logging.getLogger("retry")
    retry_logger.setLevel(logging.WARNING)
    retry_logger.addHandler(_rotating("retry.log", logging.WARNING))

    # ------------------------------------------------------------------
    # statistics logger  (structured JSON)
    # ------------------------------------------------------------------
    stats_logger = logging.getLogger("statistics")
    stats_logger.setLevel(logging.INFO)
    stats_handler = logging.handlers.RotatingFileHandler(
        log_path / "statistics.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    stats_handler.setFormatter(logging.Formatter("%(message)s"))
    stats_logger.addHandler(stats_handler)
    stats_logger.propagate = False

    # ------------------------------------------------------------------
    # Root console logger  (Rich)
    # ------------------------------------------------------------------
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    rich_handler = RichHandler(
        level=con_level,
        rich_tracebacks=True,
        show_time=True,
        show_path=False,
        markup=True,
    )
    root_logger.addHandler(rich_handler)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "asyncio", "playwright", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_statistics(stats: dict) -> None:
    """
    Write a statistics snapshot to statistics.log as JSON Lines.

    Args:
        stats: Dictionary of statistics to log.
    """
    logger = logging.getLogger("statistics")
    record = {"timestamp": datetime.now(UTC).isoformat(), **stats}
    logger.info(json.dumps(record))


def get_crawl_logger() -> logging.Logger:
    """Return the crawl logger."""
    return logging.getLogger("crawl")


def get_error_logger() -> logging.Logger:
    """Return the error logger."""
    return logging.getLogger("error")


def get_retry_logger() -> logging.Logger:
    """Return the retry logger."""
    return logging.getLogger("retry")

