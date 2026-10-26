"""A responsive native child button hosted in measured free taskbar space.

Explorer does not reserve this slot. No shell code or native control is modified.
Only fast window-manager queries and drawing run on this input-attached thread.
"""

import ctypes
from ctypes import wintypes
import queue
import sys
import threading

import win32api
import win32con as C
import win32gui as W

from core.logger import logger
from interfaces.taskbar.geometry import native_obstacle, widget_slot
from interfaces.taskbar.windows import ICON_PATH

HOST_CLASS = "FridayTaskbarHost"
BUTTON_CLASS = "FridayTaskbarButton"
ACTIVATE = C.WM_APP + 41
STOP = C.WM_APP + 42
HOTKEY_ID = 71
HOTKEY = "Ctrl+Alt+Shift+F"
STATUS = {
    "offline": ("Offline", 0x79BAE5), "online": ("Ready", 0xB3ED84),
    "listening": ("Listening", 0x00B4FF), "wake": ("Hey Friday", 0xFFAA66),
    "conversation": ("Talking", 0xFF99BB), "busy": ("Working...", 0xB3ED84),
}

user = ctypes.WinDLL("user32", use_last_error=True)
user.GetWindowDpiAwarenessContext.argtypes = [wintypes.HWND]
user.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
user.GetDpiForWindow.argtypes = [wintypes.HWND]
user.GetDpiForWindow.restype = wintypes.UINT
user.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user.SetTimer.restype = ctypes.c_size_t
user.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]


def taskbar_layout():
    """Read native group bounds; incomplete/unknown layouts produce no button."""
    bar = W.FindWindow("Shell_TrayWnd", None)
    if not bar:
        return None
    user.SetThreadDpiAwarenessContext(user.GetWindowDpiAwarenessContext(bar))
    bounds, groups, obstacles = W.GetWindowRect(bar), {}, []

    def visit(hwnd, unused):
        name = W.GetClassName(hwnd)
        if name == BUTTON_CLASS:
            return
        rect = W.GetWindowRect(hwnd)
        if name == "MSTaskListWClass":
            groups["apps"] = rect
        elif name == "TrayNotifyWnd":
            groups["tray"] = rect
        if W.IsWindowVisible(hwnd) or name == "Start":
            obstacle = native_obstacle(bounds, rect, name)
            if obstacle:
                obstacles.append(obstacle)

    W.EnumChildWindows(bar, visit, None)
    # Some shell states omit direct children from enumeration; measure them too.
    child = W.FindWindowEx(bar, 0, None, None)
    while child:
        visit(child, None)
        child = W.FindWindowEx(bar, child, None, None)
    if not {"apps", "tray"} <= groups.keys():
        return bar, bounds, None, 96
    dpi = user.GetDpiForWindow(bar) or 96
    slot = widget_slot(bounds, groups["apps"], groups["tray"], obstacles, dpi)
    return bar, bounds, slot, dpi


class TaskbarButton:
    def __init__(self, activate, state=lambda: "offline", show=None):
        self._activate, self._state = activate, state
        self._show = show or activate
        self.hwnd = self.button = None
        self.rect = None
        self._parent = self._placement = None
        self._status, self._hover = "offline", False
        self._ready = threading.Event()
        self._error = None
        self._errors = queue.SimpleQueue()
        self._hotkey_registered = False
        self._fonts, self._icon = [], None
        self._thread = threading.Thread(target=self._run, name="friday-taskbar-button", daemon=True)

    def start(self):
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("FRIDAY's taskbar button could not initialize")
        if self._error:
            raise self._error

    def stop(self):
        if self.hwnd and W.IsWindow(self.hwnd):
            W.PostMessage(self.hwnd, STOP, 0, 0)
        if self._thread.ident is not None:
            self._thread.join(timeout=5)

    def report_errors(self):
        """Log from the controller thread, outside Explorer's input queue."""
        while not self._errors.empty():
            message, info = self._errors.get_nowait()
            if info:
                logger.error(message, exc_info=info)
            else:
                logger.warning(message)

    def _run(self):
        instance, registered = win32api.GetModuleHandle(None), []
        try:
            self._icon = W.LoadImage(0, str(ICON_PATH), C.IMAGE_ICON, 32, 32, C.LR_LOADFROMFILE)
            for name in (HOST_CLASS, BUTTON_CLASS):
                wc = W.WNDCLASS()
                wc.hInstance, wc.lpszClassName, wc.lpfnWndProc = instance, name, self._proc
                wc.hCursor = W.LoadCursor(0, C.IDC_HAND)
                W.RegisterClass(wc)
                registered.append(name)
            self._taskbar_created = W.RegisterWindowMessage("TaskbarCreated")
            self.hwnd = W.CreateWindowEx(C.WS_EX_TOOLWINDOW, HOST_CLASS, "FRIDAY widget host",
                                        C.WS_POPUP, 0, 0, 0, 0, 0, 0, instance, None)
            try:
                W.RegisterHotKey(self.hwnd, HOTKEY_ID, C.MOD_CONTROL | C.MOD_ALT | C.MOD_SHIFT | 0x4000, ord("F"))
                self._hotkey_registered = True
            except W.error:
                self._hotkey_registered = False
                self._errors.put((f"Could not register {HOTKEY} for FRIDAY's flyout", None))
            if not user.SetTimer(self.hwnd, 1, 500, None):
                raise ctypes.WinError(ctypes.get_last_error())
            self._refresh()
            self._ready.set()
            W.PumpMessages()
        except Exception as error:
            self._error = error
            self._errors.put(("FRIDAY taskbar host failed", sys.exc_info()))
        finally:
            self._ready.set()
            if self.hwnd and W.IsWindow(self.hwnd):
                user.KillTimer(self.hwnd, 1)
                if self._hotkey_registered:
                    W.UnregisterHotKey(self.hwnd, HOTKEY_ID)
                if self.button and W.IsWindow(self.button):
                    W.DestroyWindow(self.button)
                W.DestroyWindow(self.hwnd)
            self._release_drawing()
            for name in reversed(registered):
                W.UnregisterClass(name, instance)
            self.hwnd = self.button = None

    def _release_fonts(self):
        for font in self._fonts:
            W.DeleteObject(font)
        self._fonts = []

    def _release_drawing(self):
        self._release_fonts()
        if self._icon:
            W.DestroyIcon(self._icon)
            self._icon = None

    def _hide(self):
        self.rect = None
        if self.button and W.IsWindow(self.button):
            W.ShowWindow(self.button, C.SW_HIDE)

    def _refresh(self):
        layout = taskbar_layout()
        if not layout:
            self._hide()
            return
        parent, bar, slot, dpi = layout
        if self.button and (not W.IsWindow(self.button) or W.GetParent(self.button) != parent):
            if W.IsWindow(self.button):
                W.DestroyWindow(self.button)
            self.button = None
        if not slot:
            self._hide()
            return
        if not self.button:
            user.SetThreadDpiAwarenessContext(user.GetWindowDpiAwarenessContext(parent))
            self.button = W.CreateWindowEx(C.WS_EX_NOPARENTNOTIFY | C.WS_EX_LAYERED, BUTTON_CLASS, "FRIDAY - Offline",
                                          C.WS_CHILD | C.WS_TABSTOP | C.WS_CLIPSIBLINGS,
                                          0, 0, 1, 1, parent, 0, win32api.GetModuleHandle(None), None)
            # Give GDI its own composited surface above the taskbar's XAML layer.
            W.SetLayeredWindowAttributes(self.button, 0, 255, C.LWA_ALPHA)
            self._parent = parent
            self._placement = None
        scale = dpi / 96
        if not self._fonts or getattr(self, "_dpi", None) != dpi:
            self._release_fonts()
            self._dpi = dpi
            for size, weight in ((12, 600), (10, 400)):
                font = W.LOGFONT()
                font.lfFaceName, font.lfHeight, font.lfWeight = "Segoe UI", -round(size * scale), weight
                self._fonts.append(W.CreateFontIndirect(font))
        x, y = W.ScreenToClient(parent, slot[:2])
        placement = parent, x, y, slot[2] - slot[0], slot[3] - slot[1]
        if placement != self._placement or not W.IsWindowVisible(self.button):
            W.SetWindowPos(self.button, C.HWND_TOP, *placement[1:], C.SWP_NOACTIVATE | C.SWP_SHOWWINDOW)
            self._placement = placement
        self.rect = W.GetWindowRect(self.button)
        status = self._state()
        try:
            cursor = W.GetCursorPos()
            hover = self.rect[0] <= cursor[0] < self.rect[2] and self.rect[1] <= cursor[1] < self.rect[3]
        except W.error as error:
            if error.winerror != 5:
                raise
            hover = False  # The lock screen can deny cursor access temporarily.
        if (status, hover) != (self._status, self._hover):
            self._status, self._hover = status, hover
            W.SetWindowText(self.button, "FRIDAY - " + STATUS.get(status, STATUS["offline"])[0])
            W.InvalidateRect(self.button, None, False)

    def _paint(self, hwnd, target_dc=None):
        dc, paint = W.BeginPaint(hwnd) if target_dc is None else (target_dc, None)
        try:
            left, top, width, height = W.GetClientRect(hwnd)
            scale = getattr(self, "_dpi", 96) / 96
            brush = W.CreateSolidBrush(0x303B31 if self._hover else 0x242C25)
            pen = W.CreatePen(C.PS_SOLID, 1, 0x5B7860)
            old_brush, old_pen = W.SelectObject(dc, brush), W.SelectObject(dc, pen)
            W.RoundRect(dc, 1, 1, width - 1, height - 1, round(12 * scale), round(12 * scale))
            W.SelectObject(dc, old_pen)
            W.SelectObject(dc, old_brush)
            W.DeleteObject(pen)
            W.DeleteObject(brush)
            size = round(24 * scale)
            compact = width < round(100 * scale)
            icon_x = (width - size) // 2 if compact else round(10 * scale)
            if self._icon:
                W.DrawIconEx(dc, icon_x, (height - size) // 2, self._icon, size, size, 0, 0, C.DI_NORMAL)
            if not compact and self._fonts:
                x = round(44 * scale)
                W.SetBkMode(dc, C.TRANSPARENT)
                old_font = W.SelectObject(dc, self._fonts[0])
                W.SetTextColor(dc, 0xEEF2ED)
                W.DrawText(dc, "FRIDAY", -1, (x, 0, width - 5, height // 2 + 2), C.DT_SINGLELINE | C.DT_BOTTOM)
                W.SelectObject(dc, self._fonts[1])
                label, color = STATUS.get(self._status, STATUS["offline"])
                W.SetTextColor(dc, color)
                W.DrawText(dc, label, -1, (x, height // 2 + 1, width - 5, height), C.DT_SINGLELINE | C.DT_TOP)
                W.SelectObject(dc, old_font)
        finally:
            if target_dc is None:
                W.EndPaint(hwnd, paint)

    def _click(self, show=False):
        if self._parent and W.IsWindow(self._parent):
            user.SetThreadDpiAwarenessContext(user.GetWindowDpiAwarenessContext(self._parent))
        anchor = W.GetWindowRect(self.button) if self.button and W.IsWindow(self.button) else None
        (self._show if show else self._activate)(anchor)  # Queue only; no UI or HTTP work here.

    def _proc(self, hwnd, message, wparam, lparam):
        try:
            if hwnd == self.hwnd:
                if message in (C.WM_TIMER, getattr(self, "_taskbar_created", -1)):
                    self._refresh()
                    return 0
                if message in (ACTIVATE, C.WM_HOTKEY):
                    self._click(show=message == ACTIVATE and bool(wparam))
                    return 0
                if message == STOP:
                    W.PostQuitMessage(0)
                    return 0
            if hwnd == self.button:
                if message in (C.WM_PAINT, 0x0318):  # WM_PRINTCLIENT supports capture while auto-hidden.
                    self._paint(hwnd, wparam if message == 0x0318 else None)
                    return 0
                if message == C.WM_ERASEBKGND:
                    return 1
                if message in (C.WM_LBUTTONUP, C.WM_RBUTTONUP) or (message == C.WM_KEYUP and wparam in (C.VK_RETURN, C.VK_SPACE)):
                    self._click()
                    return 0
                if message == C.WM_DESTROY:
                    self.button = None
                    self.rect = None
                    return 0
        except Exception:
            self._errors.put(("FRIDAY taskbar callback failed", sys.exc_info()))
            try:
                self._hide()
            except W.error:
                pass
        return W.DefWindowProc(hwnd, message, wparam, lparam)
