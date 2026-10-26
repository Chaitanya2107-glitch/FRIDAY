"""Windows capture and input, with physical-pixel mapping across monitors.

References: https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput
and https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html
"""

import ctypes
import io
from contextlib import contextmanager
from dataclasses import dataclass, field
from ctypes import wintypes

from PIL import Image, ImageChops, ImageGrab, ImageStat

from services.automation import keyboard
from services.computer.actions import Click, Keys, Proposal, Scroll, TypeText, validate_action
from services.vision.screen import _monitor_under_cursor, MAX_IMAGE_SIDE, JPEG_QUALITY


class DesktopError(Exception):
    """Capture or input could not safely proceed."""


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUITHREADINFO)]
    return user32


def _focus(user32) -> int:
    info = _GUITHREADINFO(cbSize=ctypes.sizeof(_GUITHREADINFO))
    if not user32.GetGUIThreadInfo(0, ctypes.byref(info)):
        raise DesktopError("I couldn't identify the focused control.")
    return info.hwndFocus or 0


@contextmanager
def _physical_pixels(user32):
    previous = user32.SetThreadDpiAwarenessContext(-4)
    if not previous:
        raise DesktopError("I couldn't establish physical screen coordinates.")
    try:
        yield
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)


@dataclass(frozen=True)
class Frame:
    image: Image.Image = field(repr=False)
    bounds: tuple[int, int, int, int]
    hwnd: int
    focus: int = 0

    def jpeg(self) -> bytes:
        buffer = io.BytesIO()
        self.image.save(buffer, "JPEG", quality=JPEG_QUALITY)
        return buffer.getvalue()

    def point(self, x: int, y: int) -> tuple[int, int]:
        if not (0 <= x < self.image.width and 0 <= y < self.image.height):
            raise DesktopError("The proposed point is outside the captured monitor.")
        left, top, right, bottom = self.bounds
        return (left + x * (right - left) // self.image.width,
                top + y * (bottom - top) // self.image.height)

    def same_view(self, other: "Frame", action: Proposal) -> bool:
        if (self.hwnd != other.hwnd or self.focus != other.focus or self.bounds != other.bounds
                or self.image.size != other.image.size):
            return False
        # Small caret/clock changes are tolerated. A changed click target is
        # checked separately, so a small new dialog cannot hide in a global mean.
        diff = ImageChops.difference(self.image, other.image)
        if max(ImageStat.Stat(diff).mean) > 1.5:
            return False
        if isinstance(action, (Click, Scroll)):
            patch = (max(0, action.x - 20), max(0, action.y - 20),
                     min(self.image.width, action.x + 21), min(self.image.height, action.y + 21))
            return max(ImageStat.Stat(diff.crop(patch)).mean) <= 2
        return True


def capture(bounds: tuple[int, int, int, int] | None = None) -> Frame:
    user32 = _user32()
    with _physical_pixels(user32):
        bounds = bounds or _monitor_under_cursor()
        hwnd = user32.GetForegroundWindow()
        focus = _focus(user32)
        if not bounds or not hwnd:
            raise DesktopError("I couldn't identify the active desktop and monitor.")
        image = ImageGrab.grab(bbox=bounds, all_screens=True).convert("RGB")
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        if user32.GetForegroundWindow() != hwnd or _focus(user32) != focus:
            raise DesktopError("The active window changed while I was looking. Try again.")
    return Frame(image, bounds, hwnd, focus)


def _mouse_events(action: Click | Scroll, frame: Frame, virtual: tuple[int, int, int, int]):
    x, y = frame.point(action.x, action.y)
    left, top, width, height = virtual
    if width <= 0 or height <= 0 or not (left <= x < left + width and top <= y < top + height):
        raise DesktopError("The monitor layout changed. Start the task again.")
    # SendInput's absolute coordinates span the entire virtual desktop, including
    # monitors left of the primary display (negative physical coordinates).
    event = keyboard.INPUT(type=0)
    event.u.mi = keyboard.MOUSEINPUT(dx=min(65535, int((x - left + .5) * 65536 / width)),
                                    dy=min(65535, int((y - top + .5) * 65536 / height)),
                                    dwFlags=0x0001 | 0x8000 | 0x4000)
    events = [event]
    if isinstance(action, Scroll):
        wheel = keyboard.INPUT(type=0)
        wheel.u.mi = keyboard.MOUSEINPUT(mouseData=(action.amount * 120) & 0xFFFFFFFF, dwFlags=0x0800)
        events.append(wheel)
    else:
        for _ in range(2 if action.action == "double_click" else 1):
            for flag in (0x0002, 0x0004):
                click = keyboard.INPUT(type=0)
                click.u.mi = keyboard.MOUSEINPUT(dwFlags=flag)
                events.append(click)
    return events


def execute(action: Proposal, frame: Frame) -> None:
    validate_action(action, frame.image.size)
    user32 = _user32()
    with _physical_pixels(user32):
        if user32.GetForegroundWindow() != frame.hwnd or _focus(user32) != frame.focus:
            raise DesktopError("The active window changed; I didn't perform the step.")
        if isinstance(action, (Keys, TypeText)) and not frame.focus:
            raise DesktopError("There is no focused control to receive text or keys.")
        if isinstance(action, (Click, Scroll)):
            virtual = tuple(user32.GetSystemMetrics(n) for n in (76, 77, 78, 79))
            keyboard._send(_mouse_events(action, frame, virtual))
        elif isinstance(action, TypeText):
            keyboard.type_text(action.text)
        elif isinstance(action, Keys):
            keyboard.press_keys(action.keys)
        else:
            raise DesktopError("This proposal is not a desktop action.")
