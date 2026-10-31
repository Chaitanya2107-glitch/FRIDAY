"""
interfaces/popup/app.py

Native Win32 command bar/hotkeys, started by the tray: Ctrl+Shift+F opens, Enter sends,
Escape/clicking away hides. Questions stay selected; the tray shows long replies.
Keyboard steps and computer commands restore app focus; computer proposals never activate.
Ctrl+Alt+F toggles Handy/auto-send; typing cancels auto-send and Escape cancels Handy.
"""

import ctypes
import os
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path

from core.logger import logger
from interfaces.tray import backend
from services.automation import keyboard
from interfaces.popup import computer as computer_bar
from interfaces.popup import automation as automation_bar
from interfaces.popup.computer import is_computer_command

from interfaces.popup.win32 import *  # noqa: F403 — user32, MSG, WM_…, VK_… (Win32 plumbing)

HANDY_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Handy" / "handy.exe"
HANDY_SEND_MS = 400  # after Handy's paste, before sending (it pastes in one go)
HANDY_PASTE_KEYS = {VK_CONTROL, VK_LCONTROL, VK_RCONTROL, ord("V")}  # Handy pastes with Ctrl+V
RESULT_SHOW_MS = 2500
ASK_SHOW_MS = 90_000  # her question stays up this long if it's neither answered nor focused
FOCUS_SETTLE_SECONDS = 0.2  # after focus goes back, before typing starts

_keep_alive = []  # holds ctypes callback objects so they aren't garbage-collected
_state = {
    "visible": False, "response": None, "response_ready": False, "awaiting_reply": False,
    "keyboard": (),         # text/keys from the last reply, to type into target_window
    "target_window": None,  # the window that was active before the bar opened
    "handy": False,         # Handy is listening for this bar: send what it pastes
    "guesses": [],          # commands offered under the box (services/activity/predict.py), Tab cycles them
    "guess_index": -1,
    "offered": [],          # guesses that were shown, until the bar reports which one was used
    "ask": False,           # showing FRIDAY's own question, not focused yet (Ctrl+Shift+F focuses it)
    "ask_text": "",
    "request_generation": 0,
    "automation_polling": False,
}
_hwnd = None
_hint_hwnd = None  # the line under the box showing the guesses
_reply_listener = None
_voice_hotkey_listener = None
_conversation_hotkey_listener = None
_chat_done_listener = None
_wake_hotkey_listener = None
_submit_listener = None


def _center_rect(width, height):
    screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
    return (screen_w - width) // 2, screen_h // 4


def _send_chat_message(text, generation=None):
    if generation is None:
        _state["request_generation"] += 1
        generation = _state["request_generation"]
    automation_job = None
    try:
        from services.screen_watch.commands import is_query
        if is_query(text):
            time.sleep(FOCUS_SETTLE_SECONDS)
            target = _state["target_window"]
            if not target or user32.GetForegroundWindow() != target:
                raise backend.BackendError("I couldn't return focus to your app. Open it and ask again.")
        computer_bar.before_request(text, _state["target_window"])
        reply = backend.chat(text)
        if _state["request_generation"] != generation:
            return
        _state["response"], _state["awaiting_reply"] = reply.text, reply.awaiting_reply
        _state["keyboard"] = reply.keyboard
        _state["command"] = reply.command
        _state["private"] = getattr(reply, "private", False)
        automation_job = reply.automation_job
    except backend.BackendError as e:
        if _state["request_generation"] != generation:
            return
        _state["response"], _state["awaiting_reply"], _state["command"] = str(e), False, False
        _state["private"] = False
    _state["automation_polling"] = automation_job is not None
    _state["response_ready"] = True
    if _chat_done_listener:
        _chat_done_listener()
    def publish(message, awaiting):
        if _state["request_generation"] != generation:
            return
        _state["response"], _state["awaiting_reply"] = message, awaiting
        _state["response_ready"] = True
        if _chat_done_listener:
            _chat_done_listener()
    if automation_job:
        try:
            automation_bar.follow(text, publish, lambda: _state["request_generation"] == generation, automation_job)
        finally:
            if _state["request_generation"] == generation:
                _state["automation_polling"] = False


def _show(hwnd, edit_hwnd):
    _state["request_generation"] += 1
    _state["automation_polling"] = False
    active = user32.GetForegroundWindow()
    if active and active != hwnd:
        _state["target_window"] = active
    user32.KillTimer(hwnd, RESULT_TIMER_ID)
    user32.SendMessageW(edit_hwnd, EM_SETREADONLY, 0, 0)
    user32.SetWindowTextW(edit_hwnd, "")
    _state["guesses"], _state["guess_index"] = [], -1
    if _hint_hwnd:
        user32.SetWindowTextW(_hint_hwnd, "")
    user32.ShowWindow(hwnd, SW_SHOW)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(edit_hwnd)
    _state["visible"] = True
    threading.Thread(target=_fetch_guesses, args=(hwnd,), daemon=True, name="bar-guesses").start()


def _fetch_guesses(hwnd):
    _state["guesses"] = backend.bar_suggestions()
    user32.PostMessageW(hwnd, WM_APP_HINT, 0, 0)


def _show_hint(edit_hwnd):
    """The guesses under the box, once they've arrived — if the box is still empty."""
    guesses = _state["guesses"]
    if not (_state["visible"] and guesses and _hint_hwnd) or user32.GetWindowTextLengthW(edit_hwnd):
        return
    _state["offered"] = list(guesses)
    user32.SetWindowTextW(_hint_hwnd, "Tab: " + "  ·  ".join(guesses))


def _next_guess(edit_hwnd):
    """Tab: put the next guess in the box (Enter runs it)."""
    guesses = _state["guesses"]
    if not guesses:
        return
    _state["offered"] = _state["offered"] or list(guesses)  # tabbed before the line showed: still counts
    _state["guess_index"] = (_state["guess_index"] + 1) % len(guesses)
    user32.SetWindowTextW(edit_hwnd, guesses[_state["guess_index"]])
    user32.SendMessageW(edit_hwnd, EM_SETSEL, 0xFFFF, 0xFFFF)  # caret at the end


def _report_guesses(sent):
    """Tell FRIDAY which shown guess was used (sent text), or that none was (None: closed) — training data."""
    from services.phone.commands import match_command as phone_command
    if sent and (phone_command(sent) or (_state.get("private") and _state.get("awaiting_reply"))):
        sent = None  # phone drafts and their confirmation never become suggestion training data
    offered, _state["offered"] = _state["offered"], []
    if offered:
        threading.Thread(target=backend.bar_outcome, args=(offered, sent), daemon=True).start()


def _hide(hwnd):
    user32.ShowWindow(hwnd, SW_HIDE)
    user32.KillTimer(hwnd, ASK_TIMER_ID)
    _state["visible"] = _state["ask"] = False
    _report_guesses(None)  # closed without sending (a sent one was already reported)
    if _state["handy"]:  # closed while Handy was listening: nothing to paste into
        _state["handy"] = False
        _run_handy("--cancel")


def _run_handy(flag: str) -> bool:
    """Handy's own remote control (`handy --toggle-transcription`, `--cancel`)."""
    if not HANDY_EXE.is_file():
        return False
    try:
        subprocess.Popen([str(HANDY_EXE), flag], creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as e:
        logger.warning(f"Couldn't run Handy {flag}: {e}")
        return False
    return True


def _handy_hotkey(hwnd, edit_hwnd):
    """Ctrl+Alt+F: open the bar and start Handy; pressed again, stop Handy (it then pastes)."""
    if _state["handy"] and _state["visible"]:
        _run_handy("--toggle-transcription")
        return
    _show(hwnd, edit_hwnd)
    if _run_handy("--toggle-transcription"):
        _state["handy"] = True
    else:
        user32.SetWindowTextW(edit_hwnd, "Handy isn't installed — type instead")
        user32.SendMessageW(edit_hwnd, EM_SETSEL, 0, -1)


def _toggle(hwnd, edit_hwnd):
    if _state["ask"]:  # her question is showing: jump in to type the answer
        _focus_ask(hwnd, edit_hwnd)
    else:
        _hide(hwnd) if _state["visible"] else _show(hwnd, edit_hwnd)


def _show_ask(hwnd, edit_hwnd):
    """FRIDAY's own question, shown without taking focus — so typing elsewhere never lands in the bar."""
    if _state["visible"] and not _state["ask"]:  # the Boss is using the bar right now: the toast is enough
        return
    active = user32.GetForegroundWindow()
    if active and active != hwnd:
        _state["target_window"] = active
    user32.KillTimer(hwnd, RESULT_TIMER_ID)
    user32.SendMessageW(edit_hwnd, EM_SETREADONLY, 1, 0)
    user32.SetWindowTextW(edit_hwnd, _state["ask_text"])
    if _hint_hwnd:
        user32.SetWindowTextW(_hint_hwnd, "Say your answer, or Ctrl+Shift+F to type it")
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    _state["visible"] = _state["ask"] = True
    user32.SetTimer(hwnd, ASK_TIMER_ID, ASK_SHOW_MS, None)


def _focus_ask(hwnd, edit_hwnd):
    """Ctrl+Shift+F on her question: focus the bar with the question selected, so typing replaces it."""
    _state["ask"] = False
    user32.KillTimer(hwnd, ASK_TIMER_ID)
    if _hint_hwnd:
        user32.SetWindowTextW(_hint_hwnd, "")
    user32.SendMessageW(edit_hwnd, EM_SETREADONLY, 0, 0)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(edit_hwnd)
    user32.SendMessageW(edit_hwnd, EM_SETSEL, 0, -1)


def _submit(hwnd, edit_hwnd):
    length = user32.GetWindowTextLengthW(edit_hwnd)
    if length == 0:
        return
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(edit_hwnd, buf, length + 1)
    text = buf.value.strip()
    if not text:
        return

    _report_guesses(text)
    if _submit_listener:
        _submit_listener(text)
    if _hint_hwnd:
        user32.SetWindowTextW(_hint_hwnd, "")
    user32.SendMessageW(edit_hwnd, EM_SETREADONLY, 1, 0)
    user32.SetWindowTextW(edit_hwnd, "Sending...")
    _state["response_ready"] = False
    _state["computer"] = is_computer_command(text)
    from services.screen_watch.commands import is_query
    _state["screen_query"] = is_query(text)
    if _state["computer"] or _state["screen_query"]:
        computer_bar.restore_target(hwnd, _state["target_window"], _hide)
    _state["request_generation"] += 1
    generation = _state["request_generation"]
    threading.Thread(target=_send_chat_message, args=(text, generation), daemon=True).start()
    user32.SetTimer(hwnd, POLL_TIMER_ID, 100, None)


def _type_steps(steps):
    time.sleep(FOCUS_SETTLE_SECONDS)
    try:
        keyboard.run_steps(steps)
    except keyboard.KeyboardError as e:
        if _reply_listener:
            _reply_listener(str(e))


def _type_into_target(hwnd, steps):
    """Hide, give focus back to the window the user was in, and type there."""
    _hide(hwnd)
    target = _state["target_window"]
    if target and user32.IsWindow(target):
        user32.SetForegroundWindow(target)
    threading.Thread(target=_type_steps, args=(steps,), daemon=True, name="friday-typing").start()


def _show_reply(hwnd, edit_hwnd):
    if _state.get("computer"):
        computer_bar.show_reply(hwnd, edit_hwnd, _state, _hint_hwnd, _reply_listener, _show_ask)
        return
    if _state.get("screen_query") or (_state.get("private") and not _state.get("command")):
        _state["ask_text"] = _state["response"]
        _state["ask"] = True  # refresh a visible private conversation, including its Sending state
        _show_ask(hwnd, edit_hwnd)
        if _hint_hwnd:
            user32.SetWindowTextW(_hint_hwnd, "Ctrl+Shift+F to reply; Esc to dismiss")
        if _reply_listener:
            _reply_listener(_state["response"], _state.get("command", False), _state.get("private", False))
        return
    steps, _state["keyboard"] = _state["keyboard"], ()
    if steps:
        _type_into_target(hwnd, steps)
        return
    reply = _state["response"]
    user32.SetWindowTextW(edit_hwnd, reply)
    if _reply_listener:  # a quick command's confirmation disappears by itself; answers stay
        if _state.get("private"):
            _reply_listener(reply, _state.get("command", False), True)
        else:
            _reply_listener(reply, _state.get("command", False))

    if _state["awaiting_reply"]:
        # FRIDAY asked a yes/no question: stay open with the question selected,
        # so typing the answer replaces it straight away.
        user32.SendMessageW(edit_hwnd, EM_SETREADONLY, 0, 0)
        user32.SendMessageW(edit_hwnd, EM_SETSEL, 0, -1)
        user32.SetFocus(edit_hwnd)
    else:
        user32.SendMessageW(edit_hwnd, EM_SETREADONLY, 1, 0)
        user32.SetTimer(hwnd, RESULT_TIMER_ID, RESULT_SHOW_MS, None)


def _make_wndproc(hwnd_box):
    def wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY:
            if wparam == VOICE_HOTKEY_ID:
                if _voice_hotkey_listener:
                    _voice_hotkey_listener()
            elif wparam == WAKE_HOTKEY_ID:
                if _wake_hotkey_listener:
                    _wake_hotkey_listener()
            elif wparam == CONVERSATION_HOTKEY_ID:
                if _conversation_hotkey_listener:
                    _conversation_hotkey_listener()
            elif wparam == HANDY_HOTKEY_ID:
                _handy_hotkey(hwnd, hwnd_box["edit"])
            else:
                _toggle(hwnd, hwnd_box["edit"])
            return 0
        if msg == WM_APP_SHOW:
            _show(hwnd, hwnd_box["edit"])
            return 0
        if msg == WM_APP_HINT:
            _show_hint(hwnd_box["edit"])
            return 0
        if msg == WM_APP_ASK:
            _show_ask(hwnd, hwnd_box["edit"])
            return 0
        if msg == WM_APP_ASK_DONE:
            if _state["ask"]:  # answered by voice (or gone stale) before anyone clicked in
                _hide(hwnd)
            return 0
        if msg == WM_ACTIVATE:
            if (wparam & 0xFFFF) == WA_INACTIVE:
                _hide(hwnd)
            elif _state["ask"]:  # clicked into her question: same as Ctrl+Shift+F
                _focus_ask(hwnd, hwnd_box["edit"])
            return 0
        if msg == WM_COMMAND and (wparam >> 16) == EN_CHANGE:
            if _state["handy"] and user32.GetWindowTextLengthW(hwnd_box["edit"]):
                user32.SetTimer(hwnd, HANDY_TIMER_ID, HANDY_SEND_MS, None)  # Handy pasted: send shortly
            return 0
        if msg == WM_TIMER:
            if wparam == POLL_TIMER_ID and _state["response_ready"]:
                if not _state.get("automation_polling"):
                    user32.KillTimer(hwnd, POLL_TIMER_ID)
                _state["response_ready"] = False
                _show_reply(hwnd, hwnd_box["edit"])
            elif wparam == RESULT_TIMER_ID:
                user32.KillTimer(hwnd, RESULT_TIMER_ID)
                _hide(hwnd)
            elif wparam == ASK_TIMER_ID:
                user32.KillTimer(hwnd, ASK_TIMER_ID)
                if _state["ask"]:
                    _hide(hwnd)
            elif wparam == HANDY_TIMER_ID:
                user32.KillTimer(hwnd, HANDY_TIMER_ID)
                if _state["handy"]:
                    _state["handy"] = False
                    _submit(hwnd, hwnd_box["edit"])
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    return wndproc


def _make_edit_subclass(main_hwnd, edit_hwnd, orig_proc):
    def edit_proc(hwnd, msg, wparam, lparam):
        if msg == WM_KEYDOWN:
            if wparam == VK_ESCAPE:
                _hide(main_hwnd)  # also cancels Handy
                return 0
            if wparam == VK_TAB:
                _next_guess(edit_hwnd)
                return 0
            if wparam not in HANDY_PASTE_KEYS:
                _state["handy"] = False  # typing yourself: no auto-send
            if wparam == VK_RETURN:
                _submit(main_hwnd, edit_hwnd)
                return 0
        if msg == WM_CHAR and wparam == VK_TAB:  # no tab character (or beep) in the box
            return 0
        return user32.CallWindowProcW(orig_proc, hwnd, msg, wparam, lparam)

    return edit_proc


def set_reply_listener(listener):
    """listener(text, is_command) is called (on the command bar's thread) for replies too long for the box."""
    global _reply_listener
    _reply_listener = listener


def set_submit_listener(listener):
    """listener(text) is called (on the command bar's thread) whenever the bar sends something."""
    global _submit_listener
    _submit_listener = listener


def set_wake_hotkey_listener(listener):
    """Called (on the command bar's thread) when Ctrl+Alt+H switches "Hey Friday" on or off."""
    global _wake_hotkey_listener
    _wake_hotkey_listener = listener


def set_chat_done_listener(listener):
    """listener() is called (on a worker thread) once a typed message has its reply."""
    global _chat_done_listener
    _chat_done_listener = listener


def set_conversation_hotkey_listener(listener):
    """Called (on the command bar's thread) when Ctrl+Alt+C starts or ends conversation mode."""
    global _conversation_hotkey_listener
    _conversation_hotkey_listener = listener


def set_voice_hotkey_listener(listener):
    """listener() is called (on the command bar's thread) when Ctrl+Alt+Space is pressed."""
    global _voice_hotkey_listener
    _voice_hotkey_listener = listener


def create():
    """Create the hidden command bar and register the hotkeys. Call on the thread that runs the loop."""
    global _hwnd
    hinstance = kernel32.GetModuleHandleW(None)
    class_name = "FridayQuickBarWindow"
    hwnd_box = {"edit": None}

    wndproc_func = WNDPROC(_make_wndproc(hwnd_box))
    _keep_alive.append(wndproc_func)

    wc = WNDCLASSW()
    wc.style = 0
    wc.lpfnWndProc = wndproc_func
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = hinstance
    wc.hIcon = None
    wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
    wc.hbrBackground = ctypes.cast(ctypes.c_void_p(COLOR_WINDOW + 1), wintypes.HBRUSH)
    wc.lpszMenuName = None
    wc.lpszClassName = class_name

    if not user32.RegisterClassW(ctypes.byref(wc)):
        raise ctypes.WinError(ctypes.get_last_error())

    width, height = 520, 70  # the box, and a line under it for the guesses
    x, y = _center_rect(width, height)

    hwnd = user32.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        class_name, "F.R.I.D.A.Y",
        WS_POPUP | WS_BORDER,
        x, y, width, height,
        None, None, hinstance, None,
    )
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())

    edit_hwnd = user32.CreateWindowExW(
        0, "EDIT", "",
        WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
        8, 8, width - 16, 28,
        hwnd, None, hinstance, None,
    )
    hwnd_box["edit"] = edit_hwnd
    global _hint_hwnd
    _hint_hwnd = user32.CreateWindowExW(  # "Tab: open spotify · resume catjang · …"
        0, "STATIC", "", WS_CHILD | WS_VISIBLE | SS_ENDELLIPSIS,
        10, 42, width - 20, 20, hwnd, None, hinstance, None,
    )

    # Keep the bar out of screen captures, so "what's on my screen?" sees what's behind it
    if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
        logger.warning("Could not hide the command bar from screen captures")

    font = gdi32.CreateFontW(-18, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Segoe UI")
    user32.SendMessageW(edit_hwnd, WM_SETFONT, font, 1)
    small = gdi32.CreateFontW(-13, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Segoe UI")
    user32.SendMessageW(_hint_hwnd, WM_SETFONT, small, 1)

    orig_edit_proc = user32.GetWindowLongPtrW(edit_hwnd, GWLP_WNDPROC)
    edit_proc_func = WNDPROC(_make_edit_subclass(hwnd, edit_hwnd, orig_edit_proc))
    _keep_alive.append(edit_proc_func)
    user32.SetWindowLongPtrW(edit_hwnd, GWLP_WNDPROC, ctypes.cast(edit_proc_func, ctypes.c_void_p))

    if not user32.RegisterHotKey(hwnd, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, ord("F")):
        logger.warning("Could not register Ctrl+Shift+F — another app may already use it")
    if not user32.RegisterHotKey(hwnd, VOICE_HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SPACE):
        logger.warning("Could not register Ctrl+Alt+Space for voice — another app may already use it")
    if not user32.RegisterHotKey(hwnd, WAKE_HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("H")):
        logger.warning('Could not register Ctrl+Alt+H for "Hey Friday" — another app may already use it')
    if not user32.RegisterHotKey(hwnd, CONVERSATION_HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("C")):
        logger.warning("Could not register Ctrl+Alt+C for conversation mode — another app may already use it")
    if not user32.RegisterHotKey(hwnd, HANDY_HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("F")):
        logger.warning("Could not register Ctrl+Alt+F for Handy — another app may already use it")

    _hwnd = hwnd


def run_message_loop():
    """Blocks until request_quit() is called."""
    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    user32.UnregisterHotKey(_hwnd, HOTKEY_ID)
    user32.UnregisterHotKey(_hwnd, VOICE_HOTKEY_ID)
    user32.UnregisterHotKey(_hwnd, WAKE_HOTKEY_ID)
    user32.UnregisterHotKey(_hwnd, HANDY_HOTKEY_ID)
    user32.UnregisterHotKey(_hwnd, CONVERSATION_HOTKEY_ID)


def request_show():
    """Thread-safe: ask the command bar's thread to show the bar."""
    if _hwnd:
        user32.PostMessageW(_hwnd, WM_APP_SHOW, 0, 0)


def request_ask(text):
    """Thread-safe: show FRIDAY's own question in the bar, without taking focus."""
    _state["ask_text"] = text
    if _hwnd:
        user32.PostMessageW(_hwnd, WM_APP_ASK, 0, 0)


def request_ask_done():
    """Thread-safe: take her question away if nobody has clicked into it."""
    if _hwnd:
        user32.PostMessageW(_hwnd, WM_APP_ASK_DONE, 0, 0)


def request_quit():
    """Thread-safe: close the command bar, which ends run_message_loop()."""
    if _hwnd:
        user32.PostMessageW(_hwnd, WM_CLOSE, 0, 0)
