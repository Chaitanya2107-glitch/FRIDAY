"""
services/automation/clipboard_history.py

Remembers the last few pieces of text copied to the clipboard, so FRIDAY can
list them and put an older one back.

Privacy: kept in memory only — never written to disk or chat memory, and gone
when FRIDAY stops. Anything an app marks as private (password managers) is skipped.
"""

import asyncio
import threading
from collections import deque

from core.logger import logger
from services.automation import clipboard
from services.automation.system_control import AutomationError

MAX_ITEMS = 20
POLL_SECONDS = 1
ERROR_BACKOFF_SECONDS = 30


def preview(text: str, limit: int = 80) -> str:
    """One line, trimmed — for numbered lists."""
    line = " ".join(text.split())
    return line if len(line) <= limit else line[:limit - 1] + "…"


class ClipboardHistory:
    def __init__(self, max_items: int = MAX_ITEMS):
        self._items: deque[str] = deque(maxlen=max_items)  # newest first
        self._lock = threading.Lock()  # the watcher records from a worker thread
        self._last_sequence: int | None = None

    def items(self) -> list[str]:
        with self._lock:
            return list(self._items)

    def record(self, text: str) -> None:
        if not text.strip():
            return
        with self._lock:
            if text in self._items:
                self._items.remove(text)
            self._items.appendleft(text)

    def check_clipboard(self) -> None:
        """Record the clipboard's text if something new was copied since the last check."""
        sequence = clipboard.sequence_number()
        if sequence == self._last_sequence:
            return
        if not clipboard.is_private():
            text = clipboard.get_text()
            if text:
                self.record(text)
        # Only after a successful read, so a busy clipboard is retried next tick.
        self._last_sequence = sequence

    def list_message(self) -> str:
        items = self.items()
        if not items:
            return "Your clipboard history is empty."
        lines = [f"{i}. {preview(text)}" for i, text in enumerate(items, start=1)]
        return (
            "Clipboard history (newest first):\n" + "\n".join(lines)
            + '\nSay "copy clipboard item 2" to put one back.'
        )

    def restore(self, number: int) -> str:
        """Put item `number` (1 = newest) back on the clipboard."""
        items = self.items()
        if not items:
            raise AutomationError("Your clipboard history is empty.")
        if not 1 <= number <= len(items):
            raise AutomationError(f"There's no clipboard item {number} — there are {len(items)}.")

        text = items[number - 1]
        try:
            clipboard.set_text(text)
        except clipboard.ClipboardError as e:
            logger.warning(f"Clipboard restore failed: {e}")
            raise AutomationError("Couldn't write to the clipboard — another app may be using it.")
        self.record(text)
        return f"Copied item {number} back to the clipboard: {preview(text, 60)}"

    def clear(self) -> str:
        with self._lock:
            self._items.clear()
        return "Clipboard history cleared."


async def watch_clipboard(history: ClipboardHistory) -> None:
    """Runs for the lifetime of the API process; started from app.py's lifespan."""
    logger.info("Clipboard history watcher started")
    while True:
        delay = POLL_SECONDS
        try:
            await asyncio.to_thread(history.check_clipboard)
        except clipboard.ClipboardError:
            pass  # another app is holding the clipboard — check_clipboard retries next tick
        except Exception as e:
            logger.error(f"Clipboard watcher error: {e}", exc_info=True)
            delay = ERROR_BACKOFF_SECONDS  # don't flood the log once a second
        await asyncio.sleep(delay)


# ── Singleton ─────────────────────────────────────────────────────────────────
clipboard_history = ClipboardHistory()
