"""A compact taskbar window over FRIDAY's existing desktop controls."""

import ctypes
import queue
import threading
import tkinter as tk

from PIL import Image, ImageTk
import win32api
import win32con
import win32gui

from core.logger import logger
from interfaces.taskbar.geometry import flyout_position
from interfaces.taskbar.windows import ICON_PATH, ROOT, WINDOW_TITLE
from interfaces.tray import backend

BG, SURFACE, TEXT, MUTED, ACCENT = "#101413", "#1b2420", "#edf2ee", "#a5b4aa", "#84edb3"


class ControlPanel:
    def __init__(self, tray, runtime, command_bar):
        self.tray, self.runtime, self.bar = tray, runtime, command_bar
        self._commands = queue.Queue()
        self._ready = threading.Event()
        self._error = None
        self._visible = False
        self._menu_open = False
        self._anchor = None
        self._dismiss_after = 0
        self.host = None
        self._thread = threading.Thread(target=self._run, name="friday-controls", daemon=True)

    def request_toggle(self, anchor=None):
        self._commands.put(("toggle", anchor))

    def request_show(self, anchor=None):
        self._commands.put(("show", anchor))

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("FRIDAY's control panel could not open.")
        if self._error:
            raise self._error

    def stop(self) -> None:
        self._commands.put(("quit", None))
        self._thread.join(timeout=5)

    def _run(self) -> None:
        try:
            self._build()
            self._ready.set()
            self.root.after(100, self._tick)
            self.root.mainloop()
        except Exception as error:
            self._error = error
            logger.exception("FRIDAY control panel failed")
            self.bar.request_quit()
        finally:
            self._ready.set()
            if hasattr(self, "root"):
                try:
                    self.root.destroy()
                except tk.TclError:
                    pass
                # Release Tcl objects on their owning thread.
                self.buttons.clear()
                self.__dict__.pop("_photo", None)
                self.__dict__.pop("_menu_variables", None)
                for key in ("status", "detail", "_menu"):
                    self.__dict__.pop(key, None)
                self.root = None

    def _label(self, parent, text, size=10, color=TEXT, **kwargs):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=color,
                        font=("Segoe UI", size), **kwargs)

    def _button(self, parent, key, text, command, accent=False):
        button = tk.Button(
            parent, text=text, command=command, bg=ACCENT if accent else SURFACE,
            fg=BG if accent else TEXT, activebackground="#a4f5ca" if accent else "#2a3c32",
            activeforeground=BG if accent else TEXT, disabledforeground="#68776e",
            relief="flat", bd=0, padx=10, pady=7, cursor="hand2",
            font=("Segoe UI", 9), takefocus=True,
        )
        self.buttons[key] = button
        return button

    def _build(self) -> None:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(WINDOW_TITLE)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.bind("<Escape>", lambda event: self.hide())
        self.buttons = {}
        if ICON_PATH.is_file():
            self.root.iconbitmap(str(ICON_PATH))
        logo = Image.open(ROOT / "assets" / "friday.png").convert("RGBA")
        logo.thumbnail((32, 32), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(logo, master=self.root)

        content = tk.Frame(self.root, bg=BG, padx=16, pady=14,
                           highlightbackground="#425e4d", highlightthickness=1)
        content.pack(fill="both", expand=True)
        header = tk.Frame(content, bg=BG)
        header.pack(fill="x", pady=(0, 10))
        tk.Label(header, image=self._photo, bg=BG).pack(side="left", padx=(0, 12))
        title = tk.Frame(header, bg=BG)
        title.pack(side="left")
        self._label(title, "F.R.I.D.A.Y", 17, anchor="w").pack(anchor="w")
        self._button(header, "close", "×", self.hide).pack(side="right")

        status = tk.Frame(content, bg=SURFACE, padx=12, pady=8)
        status.pack(fill="x", pady=(0, 10))
        self.status = self._label(status, "FRIDAY is stopped", 11, ACCENT, anchor="w")
        self.status.pack(fill="x")
        self.detail = self._label(status, "", 9, MUTED, anchor="w", wraplength=340, justify="left", height=2)
        self.detail.pack(fill="x", pady=(5, 0))

        self._button(content, "bar", "Command bar     Ctrl+Shift+F", self.open_command_bar, True).pack(fill="x")
        grid = tk.Frame(content, bg=BG)
        grid.pack(fill="x", pady=(6, 2))
        grid.columnconfigure((0, 1), weight=1, uniform="controls")
        for row, left, right in (
            (0, ("listen", "Start listening", self.tray.toggle_listening),
             ("wake", '"Hey Friday": Off', self.tray.toggle_wake)),
            (1, ("conversation", "Conversation: Off", self.tray.toggle_conversation),
             ("mic", "Stop microphone", self.tray.pause_microphone)),
        ):
            for col, (key, text, action) in enumerate((left, right)):
                self._button(grid, key, text, lambda action=action: self._voice_action(action)).grid(
                    row=row, column=col, sticky="ew", padx=(0, 5) if col == 0 else (5, 0), pady=5)

        self._button(content, "speech", "Speak voice replies: On", self.tray.toggle_speak_replies).pack(fill="x", pady=5)
        lifecycle = tk.Frame(content, bg=BG)
        lifecycle.pack(fill="x")
        for col, (key, text) in enumerate((("start", "Start FRIDAY"), ("restart", "Restart"), ("stop", "Stop FRIDAY"))):
            lifecycle.columnconfigure(col, weight=1)
            self._button(lifecycle, key, text, lambda key=key: self._lifecycle(key)).grid(
                row=0, column=col, sticky="ew", padx=(0 if col == 0 else 5, 0))
        self._button(content, "more", "All controls  ...", self._more_controls).pack(fill="x", pady=(8, 2))
        self._label(content, "Ctrl+Alt+Shift+F  ·  Click outside to close", 8, MUTED).pack(pady=(8, 0))

        self.root.update_idletasks()
        self._width, self._height = max(370, self.root.winfo_reqwidth()), self.root.winfo_reqheight()
        self.root.geometry(f"{self._width}x{self._height}")
        user = ctypes.windll.user32
        user.GetParent.argtypes = [ctypes.c_void_p]
        user.GetParent.restype = ctypes.c_void_p
        self._hwnd = user.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = win32gui.GetWindowLong(self._hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(self._hwnd, win32con.GWL_EXSTYLE,
                              (style | win32con.WS_EX_TOOLWINDOW) & ~win32con.WS_EX_APPWINDOW)

    def hide(self):
        self._visible = False
        self.root.withdraw()

    def show(self, anchor=None, start=False):
        import time
        self._anchor = anchor or self._anchor
        if self._anchor is None:
            w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            self._anchor = (w - 200, h - 60, w - 24, h)
        monitor = win32api.MonitorFromRect(self._anchor, win32con.MONITOR_DEFAULTTONEAREST)
        work = win32api.GetMonitorInfo(monitor)["Work"]
        x, y = flyout_position(self._anchor, self._width, self._height, work)
        self.root.geometry(f"{self._width}x{self._height}")
        self.root.deiconify()
        win32gui.SetWindowPos(self._hwnd, win32con.HWND_TOPMOST, x, y, self._width, self._height,
                              win32con.SWP_NOACTIVATE)
        self.root.lift()
        self._visible = True
        self._dismiss_after = time.monotonic() + .35
        try:
            win32gui.SetForegroundWindow(self._hwnd)
        except win32gui.error:
            pass
        self.root.focus_force()
        if start and not self.tray.online and not self.runtime.owned and not self.runtime.busy:
            self._lifecycle("start")

    def _outside(self):
        import time
        if not self._visible or self._menu_open or time.monotonic() < self._dismiss_after:
            return False
        try:
            foreground = win32gui.GetForegroundWindow()
            if self._anchor and foreground and win32gui.GetClassName(foreground) == "Shell_TrayWnd":
                x, y = win32gui.GetCursorPos()
                if self._anchor[0] <= x < self._anchor[2] and self._anchor[1] <= y < self._anchor[3]:
                    return False  # Let the button's release toggle the still-visible flyout.
            return bool(foreground and foreground != self._hwnd and not win32gui.IsChild(self._hwnd, foreground))
        except win32gui.error:
            return False  # Focus may change or the desktop may lock between queries.

    def open_command_bar(self) -> None:
        # Minimize first so the bar records the user's other app as its typing target.
        self.hide()
        self.root.after(200, self.bar.request_show)

    def _voice_action(self, action) -> None:
        self.hide()
        self.root.after(200, action)

    def _lifecycle(self, action: str) -> None:
        def work():
            if action in {"stop", "restart"}:
                self.tray.pause_microphone()
            self.runtime.operate(action)
            self.tray.check_status()
        threading.Thread(target=work, name=f"friday-{action}", daemon=True).start()

    def _more_controls(self) -> None:
        """Render the existing menu, including its dynamic submenus, in the panel."""
        import pystray
        self._menu_variables = []

        def build(descriptor):
            menu = tk.Menu(self.root, tearoff=False, bg=SURFACE, fg=TEXT,
                           activebackground=ACCENT, activeforeground=BG, font=("Segoe UI", 10))
            for item in descriptor:
                if item is pystray.Menu.SEPARATOR:
                    menu.add_separator()
                elif item.visible:
                    state = "normal" if item.enabled else "disabled"
                    if item.submenu:
                        menu.add_cascade(label=item.text, menu=build(item.submenu), state=state)
                    else:
                        command = lambda item=item: self._menu_action(item)
                        if item.checked is not None:
                            var = tk.BooleanVar(master=self.root, value=item.checked)
                            self._menu_variables.append(var)
                            menu.add_checkbutton(label=item.text, command=command, variable=var, state=state)
                        else:
                            menu.add_command(label=item.text, command=command, state=state)
            return menu

        if hasattr(self, "_menu"):
            self._menu.destroy()
        self._menu = build(self.tray.icon.menu)
        button = self.buttons["more"]
        self._menu_open = True
        try:
            self._menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally:
            self._menu.grab_release()
            self._menu_open = False
            import time
            self._dismiss_after = time.monotonic() + .2

    def _menu_action(self, item) -> None:
        self.hide()
        self.root.after(200, lambda: item(self.tray.icon))

    def _tick(self) -> None:
        if self.host:
            self.host.report_errors()
        while not self._commands.empty():
            command, anchor = self._commands.get_nowait()
            if command == "quit":
                self.root.quit()
                return
            if command == "toggle" and self._visible:
                self.hide()
            else:
                self.show(anchor, start=command in {"show", "toggle"})
        if self._outside():
            self.hide()
        online, busy = self.tray.online, self.runtime.busy
        body = self.tray.body
        if online and body and body._thread.ident is None:
            body.start()
        title = {"online": "Ready when you are", "offline": "FRIDAY is stopped",
                 "listening": "Listening...", "wake": 'Listening for "Hey Friday"',
                 "conversation": "In conversation"}[self.tray.status]
        self.status.configure(text="●  " + (self.runtime.message if busy else title),
                              fg=ACCENT if online else "#e5ba79")
        provider = backend.settings.provider or self.tray.default_provider or "Connecting"
        detail = f"{provider.title()}  |  {self.tray.mode_text()}"
        if online and not self.runtime.owned and not busy:
            detail += "\nBackend started elsewhere; manage it in its terminal."
        self.detail.configure(text=detail if online and not busy else self.runtime.message)
        for key in ("bar", "listen", "wake", "conversation", "mic"):
            self.buttons[key].configure(state="normal" if online and not busy else "disabled")
        self.buttons["listen"].configure(text="Stop listening" if self.tray.listening else "Start listening")
        self.buttons["wake"].configure(text=f'"Hey Friday": {"On" if self.tray.wake_on else "Off"}')
        self.buttons["conversation"].configure(text=f'Conversation: {"On" if self.tray.in_conversation else "Off"}')
        self.buttons["speech"].configure(text=f'Speak voice replies: {"On" if backend.settings.speak_replies else "Off"}')
        for key in ("restart", "stop"):
            self.buttons[key].configure(state="normal" if self.runtime.owned and not busy else "disabled")
        self.buttons["start"].configure(state="normal" if not online and not busy else "disabled")
        self.root.after(350, self._tick)
