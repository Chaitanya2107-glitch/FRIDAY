"""
interfaces/body/sensors.py

What FRIDAY's body senses: where the cursor is, how long since any input, whether something is
fullscreen (a game, a video — she hides), and how much you're typing and scrolling.

Typing and scrolling come from low-level Windows hooks on their own thread. Only COUNTS are kept —
never which key — and FRIDAY's own typed text (injected input) isn't counted. The hook callbacks do
nothing but add one, so they can't slow your keyboard down.
"""

import ctypes
import threading
import time
from ctypes import wintypes

from core.logger import logger

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_SYSKEYDOWN, WM_MOUSEWHEEL, WM_MOUSEHWHEEL, WM_QUIT = 0x0100, 0x0104, 0x020A, 0x020E, 0x0012
LLKHF_INJECTED = 0x10
QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE = 2, 3, 4

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = LRESULT


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def cursor() -> tuple[int, int]:
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def idle_seconds() -> float:
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


def fullscreen() -> bool:
    """A fullscreen game, video or presentation is in front: she gets out of the way."""
    state = ctypes.c_int()
    try:
        return ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0 and state.value in (
            QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE)
    except OSError:
        return False


def work_area() -> tuple[int, int, int, int]:
    """The screen minus the taskbar: (left, top, right, bottom)."""
    rect = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    return rect.left, rect.top, rect.right, rect.bottom


class InputCounter:
    """Counts key presses and scroll-wheel notches, system-wide, on its own thread."""

    def __init__(self):
        self.keys = 0
        self.wheel = 0
        self.last_key = 0.0  # time.monotonic() of the last key press (conversation mode: typing ≠ silence)
        self._procs = (HOOKPROC(self._keyboard), HOOKPROC(self._mouse))  # kept alive
        self._thread = threading.Thread(target=self._run, name="friday-body-input", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def take(self) -> tuple[int, int]:
        """(keys, wheel) since the last call."""
        keys, wheel = self.keys, self.wheel
        self.keys -= keys
        self.wheel -= wheel
        return keys, wheel

    def _keyboard(self, code, wparam, lparam):
        if code >= 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            if not ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.flags & LLKHF_INJECTED:
                self.keys += 1
                self.last_key = time.monotonic()
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _mouse(self, code, wparam, lparam):
        if code >= 0 and wparam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            self.wheel += 1
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self) -> None:
        hooks = [user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._procs[0], None, 0),
                 user32.SetWindowsHookExW(WH_MOUSE_LL, self._procs[1], None, 0)]
        if not all(hooks):
            logger.warning("FRIDAY's body can't feel typing/scrolling (the input hooks were refused)")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:  # the hooks need this thread's message loop
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
