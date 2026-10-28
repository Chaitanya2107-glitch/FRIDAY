"""Read-only active-window capture. COM and potentially stalled UIA stay in a worker."""
import ctypes
from ctypes import wintypes
import hashlib
import inspect
import io
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import psutil

from services.activity.log import IGNORED_PROCESSES, PASSWORD_MANAGERS, PRIVATE_SITE, PRIVATE_TITLE
from services.screen_watch.inference import SENSITIVE

BADGE_TITLE = "FRIDAY screen awareness"
BROWSERS = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi"}
EXCLUDED = PASSWORD_MANAGERS | IGNORED_PROCESSES | {"cmd", "powershell", "pwsh", "windowsterminal", "credentialuibroker"}
PRIVATE = re.compile(r"payment|credit.?card|card number|\bcvv\b|seed phrase|private key|"
                     r"\.env\b|credentials?|secret|one.time code|two.factor|\botp\b", re.I)


def foreground():
    if os.name != "nt":
        return None
    try:
        import win32gui
        import win32process
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return None
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        process = psutil.Process(pid)
        title = win32gui.GetWindowText(hwnd)[:512]
        app = process.name().lower().removesuffix(".exe")
        scope = {"hwnd": hwnd, "pid": pid, "created": process.create_time(),
                 "title_hash": hashlib.sha256(title.encode()).hexdigest()}
        return {"scope": scope, "app": app, "title": title}
    except Exception:
        return None


def blocked(window):
    if not window:
        return True
    return bool(window["app"] in EXCLUDED or not window["title"].strip()
                or PRIVATE_TITLE.search(window["title"]) or PRIVATE.search(window["title"])
                or window["title"].lower().startswith(("friday", "f.r.i.d.a.y")))


def indicator(hwnd):
    """A native visible badge is a prerequisite, including in headless backend runs."""
    try:
        import win32gui
        import win32process
        if (type(hwnd) is not int or not hwnd or not win32gui.IsWindowVisible(hwnd)
                or win32gui.IsIconic(hwnd) or win32gui.GetWindowText(hwnd) != BADGE_TITLE):
            return None
        dwm = ctypes.windll.dwmapi.DwmGetWindowAttribute
        dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.restype = ctypes.c_long
        cloaked = wintypes.DWORD()
        if dwm(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) or cloaked.value:
            return None
        style = win32gui.GetWindowLong(hwnd, -20)
        if not style & 8 or style & 0x80000:  # topmost, never a transparent/layered indicator
            return None
        import win32api
        rect = win32gui.GetWindowRect(hwnd)
        monitor = win32api.MonitorFromWindow(hwnd, 0)
        if not monitor:
            return None
        bounds = win32api.GetMonitorInfo(monitor)["Monitor"]
        if not (100 <= rect[2] - rect[0] <= 700 and 18 <= rect[3] - rect[1] <= 120
                and bounds[0] <= rect[0] < rect[2] <= bounds[2]
                and bounds[1] <= rect[1] < rect[3] <= bounds[3]):
            return None
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        process = psutil.Process(pid)
        launch = Path(__file__).resolve().parents[2] / "interfaces/taskbar/launch.py"
        if not any(Path(arg).is_absolute() and Path(arg).resolve() == launch for arg in process.cmdline()[1:]):
            return None
        return {"hwnd": hwnd, "pid": pid, "created": process.create_time()}
    except Exception:
        return None


def indicator_valid(expected):
    return bool(expected and indicator(expected.get("hwnd")) == expected)


def inspect_controls(root, *, browser=False):
    """Only visible text and URL identity. Password presence suppresses the whole frame."""
    todo, texts, seen, url = [(root, 0, False)], [], 0, None
    while todo:
        control, depth, inside_document = todo.pop(0)
        seen += 1
        if seen > 250 or depth > 9:
            return {"blocked": "privacy_scan_incomplete"}
        info = control.element_info
        # Read this before Name, Value or Text patterns.
        if bool(info.element.CurrentIsPassword):
            return {"blocked": "private_window"}
        if not info.visible:
            continue
        name = str(info.name or "")
        if len(name) > 4000:
            return {"blocked": "privacy_scan_incomplete"}
        if PRIVATE_TITLE.search(name) or PRIVATE.search(name) or SENSITIVE.search(name):
            return {"blocked": "private_window"}
        kind = info.control_type
        if kind in {"Text", "Document"} and name:
            texts.append(name[:500])
        if browser and not inside_document and kind == "Edit" and (
                name.lower() in {"address and search bar", "search or enter address", "address bar", "location"}
                or str(info.automation_id).lower() in {"addresseditbox", "urlbar-input", "omnibox"}):
            value = str(control.get_value() or "")[:2048]
            if not value or PRIVATE_SITE.search(value) or PRIVATE.search(value):
                return {"blocked": "private_window"}
            parsed = urlsplit(value if "://" in value else "https://" + value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                    or not re.fullmatch(r"[a-z0-9.-]+", parsed.hostname)
                    or ("." not in parsed.hostname and parsed.hostname != "localhost")):
                return {"blocked": "privacy_scan_incomplete"}
            candidate = hashlib.sha256(value.encode()).hexdigest()
            if url and url != candidate:
                return {"blocked": "privacy_scan_incomplete"}
            url = candidate
        if kind == "Document" or (kind == "Edit" and not browser):
            try:
                ranges = control.iface_text.GetVisibleRanges()
                if ranges.Length > 4:
                    return {"blocked": "privacy_scan_incomplete"}
                for i in range(ranges.Length):
                    fragment = ranges.GetElement(i).GetText(4001)
                    if len(fragment) > 4000:
                        return {"blocked": "privacy_scan_incomplete"}
                    if PRIVATE_TITLE.search(fragment) or PRIVATE.search(fragment) or SENSITIVE.search(fragment):
                        return {"blocked": "private_window"}
                    texts.append(fragment)
            except Exception:
                pass  # Names may suffice; never substitute the offscreen DocumentRange.
        children = control.children()
        if len(children) + seen + len(todo) > 250:
            return {"blocked": "privacy_scan_incomplete"}
        todo.extend((child, depth + 1, inside_document or kind == "Document") for child in children)
    if browser and not url:
        return {"blocked": "privacy_scan_incomplete"}
    text = "\n".join(dict.fromkeys(str(t).strip() for t in texts if str(t).strip()))[:4000]
    if SENSITIVE.search(text) or PRIVATE_TITLE.search(text) or PRIVATE.search(text):
        return {"blocked": "private_window"}
    return {"text": text, "url_hash": url, "content_hash": hashlib.sha256(text.encode()).hexdigest()}


class ScreenReader:
    """Lives entirely inside ProcessRuntime's owned COM apartment."""
    def __init__(self, stopped):
        self.stopped, self.desktop = stopped, None

    def _check(self, expected, badge):
        if self.stopped.is_set() or not indicator_valid(badge):
            raise InterruptedError("Screen reading paused")
        current = foreground()
        if blocked(current) or current["scope"] != expected["scope"]:
            raise InterruptedError("Foreground changed")

    def read(self, expected, badge):
        self._check(expected, badge)
        if self.desktop is None:
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
            from pywinauto import Desktop
            self.desktop = Desktop(backend="uia")
        root = self.desktop.window(handle=expected["scope"]["hwnd"]).wrapper_object()
        data = inspect_controls(root, browser=expected["app"] in BROWSERS)
        self._check(expected, badge)
        return data

    def image(self, expected, badge):
        from PIL import ImageGrab
        before = self.read(expected, badge)
        if before.get("blocked"):
            return before
        if "window" not in inspect.signature(ImageGrab.grab).parameters:
            raise ValueError("Active-window capture is unavailable")
        user = ctypes.WinDLL("user32")
        user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        try:
            with ImageGrab.grab(window=expected["scope"]["hwnd"]) as original:
                with original.convert("RGB") as frame:
                    frame.thumbnail((1024, 1024))
                    buffer = io.BytesIO()
                    frame.save(buffer, format="JPEG", quality=75)
                    image = buffer.getvalue()
        finally:
            user.SetThreadDpiAwarenessContext(previous)
        after = self.read(expected, badge)
        if (after.get("blocked") or after.get("url_hash") != before.get("url_hash")
                or after.get("content_hash") != before.get("content_hash")):
            return {"blocked": "private_window"}
        return {**after, "image": image}

    def close(self):
        if self.desktop is not None:
            self.desktop = None
            import pythoncom
            pythoncom.CoUninitialize()
