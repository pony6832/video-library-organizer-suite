"""Log files under the per-user runtime data directory.

``app.log`` records the desktop window (unhandled errors included);
``worker.log`` receives the catalog and analysis workers' output, which used
to be discarded. Both are kept small by rotating once they pass ``MAX_BYTES``.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 3
APP_LOG = "app.log"
WORKER_LOG = "worker.log"


# Tests and diagnostics can redirect the logs away from the user's profile.
LOG_DIRECTORY_ENV = "VIDEO_LIBRARY_ORGANIZER_LOG_DIR"


def log_directory() -> Path:
    override = os.environ.get(LOG_DIRECTORY_ENV)
    if override:
        return Path(override)
    from .setup_environment import app_data_root

    return app_data_root() / "logs"


def configure_app_logging() -> logging.Logger:
    """Send the ``media_catalog`` logger to app.log; safe to call twice."""
    logger = logging.getLogger("media_catalog")
    if any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        return logger
    try:
        directory = log_directory()
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / APP_LOG, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
    except OSError:
        # A read-only profile must not stop the program from starting.
        return logger
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    def log_unhandled(error_type, error, traceback) -> None:
        logger.error("Unhandled error", exc_info=(error_type, error, traceback))
        sys.__excepthook__(error_type, error, traceback)

    sys.excepthook = log_unhandled
    return logger


def open_worker_log(header: str):
    """Binary append handle for a worker's stdout/stderr, or None if unavailable."""
    try:
        directory = log_directory()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / WORKER_LOG
        if path.is_file() and path.stat().st_size > MAX_BYTES:
            for index in range(BACKUPS, 0, -1):
                older = path.with_name(f"{WORKER_LOG}.{index}")
                newer = path if index == 1 else path.with_name(f"{WORKER_LOG}.{index - 1}")
                if newer.is_file():
                    os.replace(newer, older)
        handle = open(path, "ab")
        handle.write(f"\n===== {header} =====\n".encode("utf-8"))
        handle.flush()
        return handle
    except OSError:
        return None
