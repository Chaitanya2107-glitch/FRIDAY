"""
services/automation/clipboard.py

Plain-text clipboard access through the Win32 API (ctypes) — no extra dependency.
"""

import ctypes
from dataclasses import dataclass, field
import ntpath
import os
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
CLOUD_OPT_OUT_FORMAT = "CanUploadToCloudClipboard"
OWN_FORMAT = "FRIDAY.ClipboardWriter"

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
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
user32.GetClipboardOwner.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


@dataclass(frozen=True)
class ClipboardSnapshot:
    sequence: int
    text: str | None = field(default=None, repr=False)
    sensitive: bool = False
    own: bool = False


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


def _set_bytes(format_id, data, size):
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        raise ClipboardError("out of memory")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise ClipboardError("couldn't lock clipboard memory")
    ctypes.memmove(pointer, data, size)
    kernel32.GlobalUnlock(handle)
    if not user32.SetClipboardData(format_id, handle):
        kernel32.GlobalFree(handle)
        raise ClipboardError("couldn't write to the clipboard")


def set_text(text: str, *, private: bool = False, expected_sequence: int | None = None) -> int:
    """Replace the clipboard contents with text."""
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)

    # SetClipboardData fails if the clipboard was opened without an owner window,
    # so borrow an invisible one for the duration of the write.
    owner = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    try:
        _open_clipboard(owner)
        try:
            if expected_sequence is not None and sequence_number() != expected_sequence:
                raise ClipboardError('clipboard changed before copy')
            if not user32.EmptyClipboard():
                raise ClipboardError("couldn't clear the clipboard")
            _set_bytes(user32.RegisterClipboardFormatW(OWN_FORMAT), ctypes.byref(ctypes.c_uint32(1)), 4)
            if private:
                for name in (HISTORY_OPT_OUT_FORMAT, CLOUD_OPT_OUT_FORMAT):
                    _set_bytes(user32.RegisterClipboardFormatW(name), ctypes.byref(ctypes.c_uint32(0)), 4)
                _set_bytes(user32.RegisterClipboardFormatW(EXCLUDE_FORMATS[0]), ctypes.byref(ctypes.c_uint32(1)), 4)
            _set_bytes(CF_UNICODETEXT, data, size)
            return sequence_number()  # Capture our sequence before releasing the lock.
        finally:
            user32.CloseClipboard()
    finally:
        if owner:
            user32.DestroyWindow(owner)


def sequence_number() -> int:
    """Changes every time anything is copied — cheap to poll, doesn't open the clipboard."""
    return user32.GetClipboardSequenceNumber()


def _is_private_open() -> bool:
    """Caller holds the clipboard lock; inspect flags before obtaining text."""
    if any(user32.IsClipboardFormatAvailable(user32.RegisterClipboardFormatW(name)) for name in EXCLUDE_FORMATS):
        return True

    for name in (HISTORY_OPT_OUT_FORMAT, CLOUD_OPT_OUT_FORMAT):
        opt_out = user32.RegisterClipboardFormatW(name)
        if not user32.IsClipboardFormatAvailable(opt_out):
            continue
        handle = user32.GetClipboardData(opt_out)
        if not handle or kernel32.GlobalSize(handle) < 4:
            return True
        pointer = kernel32.GlobalLock(handle) if handle else None
        if not pointer:
            return True  # the app flagged it but the flag can't be read — don't record
        try:
            if ctypes.c_uint32.from_address(pointer).value != 1:
                return True
        finally:
            kernel32.GlobalUnlock(handle)
    return False


def is_private() -> bool:
    """True if history/monitoring/cloud exclusion was requested."""
    _open_clipboard()
    try:
        return _is_private_open()
    finally:
        user32.CloseClipboard()


def _owner_identity():
    hwnd = user32.GetClipboardOwner()
    pid = wintypes.DWORD()
    if not hwnd or not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return None, None
    if pid.value == os.getpid():
        return pid.value, 'friday'
    process = kernel32.OpenProcess(0x1000, False, pid.value)
    if not process:
        return pid.value, None
    try:
        name, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not kernel32.QueryFullProcessImageNameW(process, 0, name, ctypes.byref(length)):
            return pid.value, None
        return pid.value, ntpath.basename(name.value).lower().removesuffix('.exe')
    finally:
        kernel32.CloseHandle(process)


def read_snapshot(blocklist=()) -> ClipboardSnapshot:
    """Atomic privacy-aware read. Private/blocked/own text is never obtained."""
    _open_clipboard()
    try:
        sequence = sequence_number()
        own = user32.IsClipboardFormatAvailable(user32.RegisterClipboardFormatW(OWN_FORMAT))
        if own:
            return ClipboardSnapshot(sequence, own=True)
        if _is_private_open():
            return ClipboardSnapshot(sequence, sensitive=True)
        pid, app = _owner_identity()
        if pid == os.getpid() or app in {'friday', 'friday-island', 'friday_island'}:
            return ClipboardSnapshot(sequence, own=True)
        blocked = {ntpath.basename(name).lower().removesuffix('.exe') for name in blocklist}
        if app is None or app in blocked:
            return ClipboardSnapshot(sequence, sensitive=True)
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ClipboardSnapshot(sequence)
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        size = kernel32.GlobalSize(handle) if handle else 0
        if not size or size > 131074 or size % 2:
            return ClipboardSnapshot(sequence)
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise ClipboardError('clipboard text unavailable')
        try:
            # GlobalSize can include allocator padding. Stop at an aligned UTF-16
            # terminator before decoding; padding is not part of the copied text.
            raw = ctypes.string_at(pointer, size)
            end = next((i for i in range(0, size, 2) if raw[i:i + 2] == b'\0\0'), None)
            if end is None:
                return ClipboardSnapshot(sequence)
            text = raw[:end].decode('utf-16-le', errors='strict')
        finally:
            kernel32.GlobalUnlock(handle)
        return ClipboardSnapshot(sequence_number(), text)
    finally:
        user32.CloseClipboard()
