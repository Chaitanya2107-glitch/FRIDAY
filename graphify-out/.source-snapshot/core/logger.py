"""
core/logger.py

Centralised logging for F.R.I.D.A.Y.
Every module imports the logger from here — never creates its own.

WHAT IT DOES:
  - Writes INFO+ logs to the terminal (so you see activity live)
  - Writes WARNING+ logs to logs/friday.log (so you can review errors later)
  - Rotating log file — max 5MB per file, keeps last 3 files (so logs don't eat disk)

HOW TO USE IN ANY FILE:
  from core.logger import logger
  logger.info("Server started")
  logger.warning("Something odd happened")
  logger.error("Something broke", exc_info=True)  # exc_info=True includes the traceback
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.config import config


def _build_logger() -> logging.Logger:
    """Build and return the configured FRIDAY logger."""

    log = logging.getLogger("friday")

    # Don't add handlers twice if this function is called more than once
    if log.handlers:
        return log

    log.setLevel(logging.DEBUG if config.DEBUG else logging.INFO)

    # ── Formatter ─────────────────────────────────────────────────────────────
    # What each log line looks like:
    # 2025-05-30 14:22:01 | INFO     | chat.py:58 | User sent a message
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console handler — always on ───────────────────────────────────────────
    # Some log messages use non-ASCII characters (e.g. "→"). Windows consoles
    # often default to a legacy codepage (cp1252) that can't encode them, so
    # force UTF-8 here rather than depending on the entry point to do it.
    if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if config.DEBUG else logging.INFO)
    console.setFormatter(fmt)
    log.addHandler(console)

    # ── File handler — writes to logs/friday.log ──────────────────────────────
    try:
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = config.LOGS_DIR / "friday.log"

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,   # 5MB max per file
            backupCount=3,               # keep last 3 rotated files
            encoding="utf-8",
        )
        file_handler.setLevel(logging.WARNING)   # only warnings+ go to file
        file_handler.setFormatter(fmt)
        log.addHandler(file_handler)

    except Exception as e:
        # If we can't write to the log file, warn on console but don't crash
        log.warning(f"Could not set up file logging: {e}")

    return log


# ── Singleton ──────────────────────────────────────────────────────────────────
# Import this everywhere. Never call logging.getLogger() yourself.
logger = _build_logger()
