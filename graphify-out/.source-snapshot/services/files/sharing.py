"""Explicit sharing of the file selected in Explorer, using FRIDAY's saved recipients."""

import threading
from pathlib import Path
from typing import Literal, NamedTuple

from core.logger import logger
from services.automation.system_control import AutomationError
from services.telegram import commands as telegram_commands

Channel = Literal["telegram", "whatsapp"]
ShareStatus = Literal["sent", "prepared", "failed"]
WHATSAPP_MAX_BYTES = 2 * 1024 ** 3
_whatsapp_lock = threading.Lock()


class ShareResult(NamedTuple):
    success: bool
    message: str
    status: ShareStatus


def share_file(selected: str, channel: Channel) -> ShareResult:
    """Send the exact selected file; paths never go through command or AI parsing."""
    if channel not in ("telegram", "whatsapp"):
        return ShareResult(False, "Choose Telegram or WhatsApp.", "failed")
    try:
        path = Path(selected)
        if not path.is_absolute() or not path.is_file():
            return ShareResult(False, "Select an available file in File Explorer, then try again.", "failed")
        if channel == "telegram":
            result = telegram_commands.run({"action": "telegram_file", "path": str(path)})
            message = f"Sent {path.name} to Chaitu through Telegram." if result.success else result.message
            return ShareResult(result.success, message, "sent" if result.success else "failed")

        if path.stat().st_size > WHATSAPP_MAX_BYTES:
            return ShareResult(False, "That file is over WhatsApp's 2 GB attachment limit.", "failed")
        if not _whatsapp_lock.acquire(blocking=False):
            return ShareResult(False, "Another WhatsApp attachment is in progress. Wait for it to finish.", "failed")
        try:
            from services.automation import whatsapp_files
            message = whatsapp_files.prepare(path, "chaitu")
            return ShareResult(True, message, "prepared")
        finally:
            _whatsapp_lock.release()
    except AutomationError as error:
        return ShareResult(False, str(error), "failed")
    except (OSError, ValueError):
        logger.warning("Selected-file sharing failed through %s", channel)
        return ShareResult(False, "I couldn't access or share that file. Check that it is still available.", "failed")
