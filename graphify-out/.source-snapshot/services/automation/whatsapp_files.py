"""Prepare a WhatsApp Desktop file preview; the user presses Send themselves."""

import ctypes
import os
import struct
import time
from pathlib import Path

from core.logger import logger
from services.activity.log import foreground_app
from services.automation import clipboard, keyboard, whatsapp
from services.automation.system_control import AutomationError

CF_HDROP = 15
MAX_FILE_BYTES = 2 * 1024 ** 3


def _file_drop_payload(path: Path) -> bytes:
    """Win32 DROPFILES followed by a double-NUL terminated Unicode file list.

    Format: https://learn.microsoft.com/en-us/windows/win32/shell/clipboard
    """
    return struct.pack("<IiiII", 20, 0, 0, 0, 1) + (str(path) + "\0\0").encode("utf-16-le")


def _copy_file(path: Path) -> None:
    """Place a file object on the clipboard without converting it to path text."""
    data = _file_drop_payload(path)
    owner = clipboard.user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    if not owner:
        raise clipboard.ClipboardError("couldn't create a clipboard owner")
    handle = None
    transferred = False
    try:
        clipboard._open_clipboard(owner)
        try:
            handle = clipboard.kernel32.GlobalAlloc(clipboard.GMEM_MOVEABLE, len(data))
            if not handle:
                raise clipboard.ClipboardError("out of memory")
            pointer = clipboard.kernel32.GlobalLock(handle)
            if not pointer:
                raise clipboard.ClipboardError("couldn't lock clipboard memory")
            try:
                ctypes.memmove(pointer, data, len(data))
            finally:
                clipboard.kernel32.GlobalUnlock(handle)
            if not clipboard.user32.EmptyClipboard():
                raise clipboard.ClipboardError("couldn't clear the clipboard")
            if not clipboard.user32.SetClipboardData(CF_HDROP, handle):
                raise clipboard.ClipboardError("couldn't write the file to the clipboard")
            transferred = True  # Windows now owns the allocation.
        finally:
            if handle and not transferred:
                clipboard.kernel32.GlobalFree(handle)
            clipboard.user32.CloseClipboard()
    finally:
        clipboard.user32.DestroyWindow(owner)


def _whatsapp_focused() -> bool:
    return (foreground_app() or "").lower().startswith("whatsapp")


def prepare(path: Path, contact: str = "chaitu") -> str:
    """Open the recipient chat and paste the file, with checks before each action."""
    path = Path(path)
    if not path.is_absolute():
        raise AutomationError("Choose a file with an absolute path to attach in WhatsApp.")
    try:
        if not path.is_file():
            raise AutomationError("That file no longer exists or is a folder.")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise AutomationError("WhatsApp attachments must be 2 GB or smaller.")
    except OSError as error:
        raise AutomationError("I couldn't access the selected file for WhatsApp.") from error

    name, number = whatsapp.recipient(contact)
    number = whatsapp.clean_number(number)
    if not number:
        raise AutomationError(f"The saved WhatsApp number for {name} is invalid.")
    try:
        os.startfile(f"whatsapp://send?phone={number}")
    except OSError as error:
        logger.warning("WhatsApp file link failed: %s", error)
        raise AutomationError("Couldn't open WhatsApp. Is WhatsApp Desktop installed?") from error

    deadline = time.monotonic() + whatsapp.WINDOW_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if _whatsapp_focused():
            break
    else:
        raise AutomationError("WhatsApp didn't come to the front. Open WhatsApp Desktop and try again; no file was attached.")
    time.sleep(whatsapp.CHAT_LOAD_SECONDS)
    if not _whatsapp_focused():
        raise AutomationError("WhatsApp lost focus. Bring it to the front and try again; no file was attached.")
    try:
        _copy_file(path)
    except clipboard.ClipboardError as error:
        raise AutomationError(f"I couldn't copy the file to the clipboard for WhatsApp: {error}.") from error
    if not _whatsapp_focused():
        raise AutomationError("WhatsApp lost focus. The file is copied; paste it into the chat and review it before pressing Send.")
    try:
        keyboard.press_keys("ctrl+v")
    except keyboard.KeyboardError as error:
        raise AutomationError("I couldn't paste the attachment into WhatsApp. The file is copied; paste it manually into the chat and review it before pressing Send.") from error
    logger.info("WhatsApp attachment paste performed for %s; awaiting the user's Send action", name)
    return f"Prepared {path.name} for {name} in WhatsApp. Review the attachment and press Send."
