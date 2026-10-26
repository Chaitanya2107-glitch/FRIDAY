"""
services/automation/clipboard.py

Plain-text clipboard access through the Win32 API (ctypes) — no extra dependency.
"""

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# Formats apps like password managers add to say "don't record this" — the same
# signals Windows' own clipboard history (Win+V) honours.
EXCLUDE_FORMATS = ("ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore")
HISTORY_OPT_OUT_FORMAT = "CanIncludeInClipboardHistory"  # holds a DWORD; 0 = don't record

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL


class ClipboardError(Exception):
    pass


def _open_clipboard(owner=None):
    # Other apps hold the clipboard briefly all the time; retry rather than fail.
    for _ in range(10):
        if user32.OpenClipboard(owner):
            return
        time.sleep(0.05)
    raise ClipboardError("the clipboard is busy")


def get_text() -> str | None:
    """Return the clipboard's text, or None if it holds no text."""
    _open_clipboard()
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_text(text: str) -> None:
    """Replace the clipboard contents with text."""
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)

    # SetClipboardData fails if the clipboard was opened without an owner window,
    # so borrow an invisible one for the duration of the write.
    owner = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    try:
        _open_clipboard(owner)
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
            if not handle:
                raise ClipboardError("out of memory")
            pointer = kernel32.GlobalLock(handle)
            ctypes.memmove(pointer, data, size)
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                raise ClipboardError("couldn't write to the clipboard")
        finally:
            user32.CloseClipboard()
    finally:
        if owner:
            user32.DestroyWindow(owner)


def sequence_number() -> int:
    """Changes every time anything is copied — cheap to poll, doesn't open the clipboard."""
    return user32.GetClipboardSequenceNumber()


def is_private() -> bool:
    """True if the app that copied the current contents asked clipboard tools not to record them."""
    if any(user32.IsClipboardFormatAvailable(user32.RegisterClipboardFormatW(name)) for name in EXCLUDE_FORMATS):
        return True

    opt_out = user32.RegisterClipboardFormatW(HISTORY_OPT_OUT_FORMAT)
    if not user32.IsClipboardFormatAvailable(opt_out):
        return False

    _open_clipboard()
    try:
        handle = user32.GetClipboardData(opt_out)
        pointer = kernel32.GlobalLock(handle) if handle else None
        if not pointer:
            return True  # the app flagged it but the flag can't be read — don't record
        try:
            return ctypes.c_uint32.from_address(pointer).value == 0
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
