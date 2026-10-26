"""Focus and non-activating proposals for computer commands in the command bar."""

import time

from interfaces.popup.win32 import user32
from interfaces.tray import backend
from services.computer.agent import is_computer_command as _computer_command
from services.browser.commands import match_command, is_desktop_command

FOCUS_SETTLE_SECONDS = .2


def is_computer_command(text):
    return _computer_command(text) or match_command(text) is not None


def before_request(text, target):
    if not is_computer_command(text):
        return
    command = match_command(text)
    if command and command.kind in {"help", "status", "stop", "report"}:
        return
    if command and command.kind != "desktop" and not is_desktop_command(text) and command.kind != "yes":
        return
    time.sleep(FOCUS_SETTLE_SECONDS)
    parts = text.strip().split(maxsplit=1)
    control = parts[1].lower() if len(parts) == 2 else "help"
    if control not in {"help", "status", "stop", "no", "cancel"}:
        if not target or user32.GetForegroundWindow() != target:
            raise backend.BackendError("I couldn't return focus to your app. Open it and try the computer command again.")


def restore_target(hwnd, target, hide):
    # Restore focus before the backend captures or executes desktop input.
    hide(hwnd)
    if target and user32.IsWindow(target):
        user32.SetForegroundWindow(target)


def show_reply(hwnd, edit_hwnd, state, hint_hwnd, listener, show_ask):
    state["ask_text"] = state["response"]
    show_ask(hwnd, edit_hwnd)  # existing popup path displays without activation
    if hint_hwnd:
        hint = ("Ctrl+Shift+F: use the approval/stop command shown above" if state["awaiting_reply"]
                else "Esc to dismiss; Ctrl+Shift+F to start another task")
        user32.SetWindowTextW(hint_hwnd, hint)
    if listener:
        listener(state["response"], False)
