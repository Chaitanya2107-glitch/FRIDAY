"""A separate, non-activating pause badge. The original desktop robot is untouched."""
import ctypes
import tkinter as tk

import win32api
import win32con
import win32gui

from services.screen_watch.capture import BADGE_TITLE


class ScreenBadge:
    def __init__(self, root, tray):
        self.tray, self._pending_pause, self._pause_epoch = tray, False, None
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.title(BADGE_TITLE)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.button = tk.Button(self.window, text="Screen awareness · Pause", command=self.pause,
                                bg="#193f32", fg="#dcffeb", activebackground="#315a47",
                                activeforeground="white", font=("Segoe UI", 9), relief="flat",
                                padx=12, pady=6, cursor="hand2", takefocus=False)
        self.button.pack()
        self.window.update_idletasks()
        user = ctypes.windll.user32
        user.GetParent.argtypes = [ctypes.c_void_p]
        user.GetParent.restype = ctypes.c_void_p
        self.hwnd = user.GetParent(self.window.winfo_id()) or self.window.winfo_id()
        style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE,
                              style | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE)

    def pause(self):
        state = (self.tray.runtime_status or {}).get("screen_watch") or {}
        self._pending_pause, self._pause_epoch = True, state.get("epoch")
        self.window.withdraw()
        self.tray.screen_indicator = 0  # immediate local revocation, before the HTTP reply
        self.tray._command_action("pause screen awareness")()

    def update(self):
        state = (self.tray.runtime_status or {}).get("screen_watch") or {}
        if (self._pending_pause and state.get("epoch") is not None and state.get("epoch") != self._pause_epoch
                and (state.get("paused") or not state.get("enabled"))):
            self._pending_pause = False
        visible = self.tray.online and state.get("enabled") and not state.get("paused") and not self._pending_pause
        if not visible:
            self.window.withdraw()
            self.tray.screen_indicator = 0
            return
        label = ("Screen blocked" if state.get("state") in {"private_window", "privacy_scan_incomplete"} else
                 "Screen unavailable" if state.get("state") == "unavailable" else "Screen awareness")
        self.button.configure(text=label + " · Pause")
        self.window.deiconify()
        monitor = win32api.MonitorFromWindow(win32gui.GetForegroundWindow(), win32con.MONITOR_DEFAULTTONEAREST)
        left, top, right, bottom = win32api.GetMonitorInfo(monitor)["Work"]
        width, height = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, right - width - 16, top + 14, width, height,
                              win32con.SWP_NOACTIVATE)
        self.tray.screen_indicator = self.hwnd if self.window.winfo_viewable() else 0
