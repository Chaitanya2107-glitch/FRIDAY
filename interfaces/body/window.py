"""
interfaces/body/window.py

FRIDAY's body on the desktop: a see-through, always-on-top window (tkinter, on its own thread inside
the tray app) showing the robot drawn by sprite.py, moved by animator.py, 30 frames a second.

  click → talk (the mic opens) · double-click → the command bar · drag → move her (she remembers where)
  right-click → a menu: talk, command bar, free will, sounds, hide, quit
  speech bubbles next to her: her own questions, reminders, "Claude needs your OK" (click one to close it)
  she hides while something is fullscreen (games, videos) and comes back after

Her mind comes from the backend (GET /api/v1/body, services/body_state.py), asked a few times a second.
Settings (position, shown or hidden, sounds) live in memory/body/state.json.
"""

import ctypes
import json
import queue
import threading
import time
import tkinter as tk

from PIL import ImageTk

from core.config import config
from core.logger import logger
from interfaces.body import sensors, sounds, sprite
from interfaces.body.animator import Animator, Inputs

state_path = config.MEMORY_DIR / "body" / "state.json"
FRAME_MS = 33
POLL_SECONDS = 0.35
FULLSCREEN_CHECK_SECONDS = 0.5
DRAG_START_PX = 4
DOUBLE_CLICK_MS = 260
BUBBLE_WIDTH = 240
KEY_HEX = "#%02x%02x%02x" % sprite.KEY
GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_APPWINDOW = -20, 0x80, 0x08000000, 0x40000


def _no_taskbar_no_focus(widget) -> None:
    """Keep her out of Alt+Tab / the taskbar, and never take focus from what you're typing in."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(widget.winfo_id()) or widget.winfo_id()
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW)


def load_state() -> dict:
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class FridayBody:
    def __init__(self, tray, command_bar, api=None):
        from interfaces.tray import backend
        self._tray, self._bar, self._api = tray, command_bar, api or backend
        saved = load_state()
        self.visible = saved.get("visible", True)
        self.sounds_on = saved.get("sounds", True)
        self._saved_pos = saved.get("x"), saved.get("y")
        self._commands: queue.Queue = queue.Queue()  # other threads → the tk thread
        self._mind: dict = {}
        self._events: list = []
        self._events_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="friday-body", daemon=True)

    # ── From other threads ────────────────────────────────────────────────────

    @property
    def last_key_at(self) -> float:
        """time.monotonic() of the Boss's last key press (0 = none yet)."""
        inputs = getattr(self, "_inputs", None)
        return inputs.last_key if inputs else 0.0

    def start(self) -> None:
        self._thread.start()

    def set_visible(self, visible: bool) -> None:
        self._commands.put(("visible", visible))

    def stop(self, wait: float = 1.0) -> None:
        self._commands.put(("stop", None))
        self._thread.join(wait)

    # ── The tk thread ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            # Real screen pixels for this thread's windows: Windows' display scaling would stretch the pixel art
            # blurry. (Cursor and work-area numbers read on this thread are then real pixels too.)
            ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
            self._build()
            threading.Thread(target=self._poll_mind, name="friday-body-mind", daemon=True).start()
            self._root.after(FRAME_MS, self._frame)
            self._root.mainloop()
        except Exception as e:
            logger.error(f"FRIDAY's body stopped: {e}", exc_info=True)
        finally:
            if hasattr(self, "_root"):
                try:
                    self._root.destroy()
                except tk.TclError:
                    pass
                # Each Tk interpreter's objects must be released on its own thread.
                for name in ("_photo", "_label", "_canvas", "_bubble", "_root"):
                    self.__dict__.pop(name, None)

    def _build(self) -> None:
        self._root = root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", KEY_HEX)
        root.configure(bg=KEY_HEX)
        self._label = tk.Label(root, bd=0, bg=KEY_HEX, highlightthickness=0)
        self._label.pack()
        self._w, self._h = sprite.W * sprite.SCALE, sprite.H * sprite.SCALE
        left, top, right, bottom = sensors.work_area()
        x, y = self._saved_pos
        if x is None or not (left - self._w < x < right and top - self._h < y < bottom):
            x, y = right - self._w - 40, bottom - self._h + 6  # bottom-right, standing on the taskbar
        self._x, self._y = int(x), int(y)
        root.geometry(f"{self._w}x{self._h}+{self._x}+{self._y}")
        root.update_idletasks()
        _no_taskbar_no_focus(root)
        for event, handler in (("<ButtonPress-1>", self._press), ("<B1-Motion>", self._motion),
                               ("<ButtonRelease-1>", self._release), ("<ButtonPress-3>", self._menu)):
            self._label.bind(event, handler)
        self._build_bubble()
        self._animator = Animator(time.monotonic())
        self._inputs = sensors.InputCounter()
        self._inputs.start()
        self._sound_files = sounds.ensure(config.MEMORY_DIR / "body" / "sounds")
        self._photo, self._last_pose = None, None
        self._drag = None           # (cursor x, y, window x, y) at the press
        self._dragging, self._drag_v, self._last_drag = False, (0.0, 0.0), None
        self._click_timer = None
        self._fullscreen, self._next_fullscreen_check = False, 0.0
        self._shown = False

    def _build_bubble(self) -> None:
        self._bubble = tk.Toplevel(self._root)
        self._bubble.withdraw()
        self._bubble.overrideredirect(True)
        self._bubble.attributes("-topmost", True)
        self._bubble.attributes("-transparentcolor", KEY_HEX)
        self._bubble.configure(bg=KEY_HEX)
        self._canvas = tk.Canvas(self._bubble, bg=KEY_HEX, highlightthickness=0, bd=0)
        self._canvas.pack()
        self._canvas.bind("<ButtonPress-1>", lambda e: self._hide_bubble())
        self._bubble_until = 0.0
        self._bubble.update_idletasks()
        _no_taskbar_no_focus(self._bubble)

    # ── Every frame ───────────────────────────────────────────────────────────

    def _frame(self) -> None:
        try:
            if self._handle_commands():
                return
            now = time.monotonic()
            if now >= self._next_fullscreen_check:
                self._fullscreen = sensors.fullscreen()
                self._next_fullscreen_check = now + FULLSCREEN_CHECK_SECONDS
            if not self.visible or self._fullscreen or not self._tray.online:
                self._show(False)
            else:
                self._show(True)
                self._animate(now)
        except Exception as e:  # one bad frame must not kill her
            logger.warning(f"FRIDAY's body frame failed: {e}")
        self._root.after(FRAME_MS, self._frame)

    def _handle_commands(self) -> bool:
        """True when told to stop."""
        while True:
            try:
                command, value = self._commands.get_nowait()
            except queue.Empty:
                return False
            if command == "stop":
                self._root.destroy()
                return True
            if command == "visible":
                self.visible = value
                self._save()

    def _show(self, show: bool) -> None:
        if show == self._shown:
            return
        self._shown = show
        if show:
            self._root.deiconify()
            self._root.attributes("-topmost", True)
        else:
            self._root.withdraw()
            self._hide_bubble()

    def _animate(self, now: float) -> None:
        cx, cy = sensors.cursor()
        centre_x, centre_y = self._x + sprite.CX * sprite.SCALE, self._y + sprite.CY * sprite.SCALE
        s = sprite.SCALE
        over_head = (self._x + (sprite.CX - 14) * s <= cx <= self._x + (sprite.CX + 14) * s
                     and self._y + (sprite.CY - 18) * s <= cy <= self._y + (sprite.CY - 7) * s)
        keys, wheel = self._inputs.take()
        with self._events_lock:
            events, self._events = self._events, []
        frame = self._animator.step(Inputs(
            t=now, cursor=(cx - centre_x, cy - centre_y), over_head=over_head and not self._dragging,
            keys=keys, wheel=wheel, idle=sensors.idle_seconds(), dragging=self._dragging,
            drag_velocity=self._drag_v, mind=dict(self._mind), events=events))
        if frame.pose != self._last_pose:
            self._photo = ImageTk.PhotoImage(sprite.render(frame.pose), master=self._root)
            self._label.configure(image=self._photo)
            self._last_pose = frame.pose
        if self.sounds_on:
            for name in frame.sounds[-1:]:
                sounds.play(self._sound_files[name])
        for text, seconds in frame.bubbles[-1:]:
            self._say(text, seconds)
        if self._bubble_until and now >= self._bubble_until:
            self._hide_bubble()

    # ── Speech bubbles ────────────────────────────────────────────────────────

    def _say(self, text: str, seconds: float) -> None:
        c = self._canvas
        c.delete("all")
        label = c.create_text(12, 10, text=text, anchor="nw", width=BUBBLE_WIDTH - 24,
                              font=("Segoe UI", 11), fill="#25243f")
        x0, y0, x1, y1 = c.bbox(label)
        w, h = x1 + 12, y1 + 10
        tail = 10
        left, top, right, bottom = sensors.work_area()
        head_x = self._x + sprite.CX * sprite.SCALE
        bx = min(max(left, head_x - w + 40), right - w)
        by = self._y + 4 * sprite.SCALE - h - tail
        tx = min(max(16, head_x - bx), w - 16)  # the tail points at her head
        c.configure(width=w, height=h + tail)
        c.create_rectangle(2, 2, w - 2, h - 2, fill="#f4f3f8", outline="#25243f", width=2)
        for x, y in ((2, 2), (w - 5, 2), (2, h - 5), (w - 5, h - 5)):  # pixel-cut corners
            c.create_rectangle(x, y, x + 3, y + 3, fill=KEY_HEX, outline="")
        c.create_polygon(tx - 7, h - 3, tx + 7, h - 3, tx, h + tail - 1, fill="#f4f3f8", outline="#25243f", width=2)
        c.create_line(tx - 5, h - 2, tx + 5, h - 2, fill="#f4f3f8", width=3)
        c.tag_raise(label)
        self._bubble.geometry(f"{w}x{h + tail}+{bx}+{max(top, by)}")
        self._bubble.deiconify()
        self._bubble.attributes("-topmost", True)
        self._bubble_until = time.monotonic() + seconds

    def _hide_bubble(self) -> None:
        self._bubble.withdraw()
        self._bubble_until = 0.0

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def _press(self, event) -> None:
        self._drag = (event.x_root, event.y_root, self._x, self._y)
        self._last_drag = (event.x_root, event.y_root, time.monotonic())

    def _motion(self, event) -> None:
        if not self._drag:
            return
        mx, my, wx, wy = self._drag
        if not self._dragging and abs(event.x_root - mx) + abs(event.y_root - my) < DRAG_START_PX:
            return
        self._dragging = True
        self._x, self._y = wx + event.x_root - mx, wy + event.y_root - my
        self._root.geometry(f"+{self._x}+{self._y}")
        lx, ly, lt = self._last_drag
        now = time.monotonic()
        dt = max(1e-3, now - lt)
        self._drag_v = ((event.x_root - lx) / dt, (event.y_root - ly) / dt)
        self._last_drag = (event.x_root, event.y_root, now)
        if self._bubble_until:
            self._hide_bubble()

    def _release(self, event) -> None:
        was_dragging, self._dragging, self._drag = self._dragging, False, None
        self._drag_v = (0.0, 0.0)
        if was_dragging:
            self._save()
            return
        if self._click_timer:  # the second click: the command bar
            self._root.after_cancel(self._click_timer)
            self._click_timer = None
            self._bar.request_show()
        else:
            self._click_timer = self._root.after(DOUBLE_CLICK_MS, self._single_click)

    def _single_click(self) -> None:
        self._click_timer = None
        self._tray.toggle_listening()  # talk (or stop listening)

    def _menu(self, event) -> None:
        menu = tk.Menu(self._root, tearoff=0)
        talk = tk.BooleanVar(master=self._root, value=self._tray.talk_on)
        chirps = tk.BooleanVar(master=self._root, value=self.sounds_on)
        menu.add_command(label="Talk to FRIDAY", command=self._tray.toggle_listening)
        menu.add_command(label="Open command bar", command=self._bar.request_show)
        menu.add_separator()
        menu.add_checkbutton(label="Let FRIDAY talk on her own", variable=talk, command=self._tray.toggle_talk)
        menu.add_checkbutton(label="Body sounds", variable=chirps, command=self._toggle_sounds)
        menu.add_command(label="Hide me (All controls → Show FRIDAY's body)", command=lambda: self.set_visible(False))
        menu.add_separator()
        menu.add_command(label="Stop FRIDAY", command=self._tray.stop_friday)
        ctypes.windll.user32.SetForegroundWindow(self._root.winfo_id())  # so the menu closes on a click elsewhere
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _toggle_sounds(self) -> None:
        self.sounds_on = not self.sounds_on
        self._save()

    def _save(self) -> None:
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"x": self._x, "y": self._y, "visible": self.visible,
                                              "sounds": self.sounds_on}), encoding="utf-8")
        except OSError as e:
            logger.warning(f"Couldn't save FRIDAY's body settings: {e}")

    # ── Her mind (a background thread) ────────────────────────────────────────

    def _poll_mind(self) -> None:
        last = None  # the newest event seen; None = just started (what happened before isn't replayed)
        while self._thread.is_alive():
            if not self._tray.online:
                self._mind = {}
                time.sleep(1)
                continue
            try:
                data = self._api.body_state(last or 0)
                events = data.pop("events", [])
                if last is not None:
                    with self._events_lock:
                        self._events.extend(events)
                last = data.pop("last", last or 0)
                self._mind = data
            except Exception:
                self._mind = {}
            time.sleep(POLL_SECONDS)
