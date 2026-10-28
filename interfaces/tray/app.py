"""
interfaces/tray/app.py

Entry point for FRIDAY's taskbar controls, command bar, hotkeys and body.

Run with: python -B -m interfaces.taskbar (or the FRIDAY shortcut).
"""

import ctypes
import threading
from ctypes import wintypes

from interfaces.body.window import FridayBody
from interfaces.popup import app as command_bar
from interfaces.tray.tray import FridayTray, is_quick_command
from interfaces.taskbar.panel import ControlPanel
from interfaces.taskbar.host import TaskbarButton
from interfaces.taskbar.runtime import BackendRuntime
from interfaces.taskbar.windows import acquire_instance, prepare_process, release_instance

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.MessageBoxW.restype = ctypes.c_int

MB_YESNO, MB_ICONWARNING, MB_TOPMOST, MB_SETFOREGROUND = 0x4, 0x30, 0x40000, 0x10000
IDYES = 6


def confirm(title: str, text: str) -> bool:
    flags = MB_YESNO | MB_ICONWARNING | MB_TOPMOST | MB_SETFOREGROUND
    return user32.MessageBoxW(None, text, title, flags) == IDYES


def main():
    prepare_process()
    handle = acquire_instance()
    if handle is None:
        return
    runtime = BackendRuntime()
    try:
        _run_desktop(runtime)
    finally:
        runtime.close()
        release_instance(handle)


def _run_desktop(runtime):
    command_bar.create()

    def stop_friday():
        def work():
            tray.pause_microphone(wait=True)
            runtime.operate("stop")
            tray.check_status()
        threading.Thread(target=work, name="friday-stop", daemon=True).start()

    tray = FridayTray(
        show_command_bar=command_bar.request_show,
        quit_app=command_bar.request_quit,
        confirm=confirm,
        ask_in_bar=command_bar.request_ask,
        ask_done=command_bar.request_ask_done,
        stop_backend=stop_friday,
    )
    command_bar.set_reply_listener(lambda text, is_command=False, private=False: tray.notify(
        text, transient=is_quick_command(is_command, text), private=private))
    command_bar.set_submit_listener(tray.bar_submitted)
    command_bar.set_voice_hotkey_listener(tray.toggle_listening)
    command_bar.set_wake_hotkey_listener(tray.toggle_wake)
    command_bar.set_conversation_hotkey_listener(tray.toggle_conversation)
    command_bar.set_chat_done_listener(tray.typed_reply_done)

    panel = ControlPanel(tray, runtime, command_bar)
    host = TaskbarButton(panel.request_toggle, state=lambda: "busy" if runtime.busy else tray.status,
                         show=panel.request_show)
    panel.host = host
    tray.body = FridayBody(tray, command_bar)
    try:
        panel.start()
        host.start()
        panel._lifecycle("start")
        threading.Thread(target=tray.run, kwargs={"show_icon": False}, name="friday-controls", daemon=True).start()
        command_bar.run_message_loop()
    finally:
        tray._stopping.set()
        tray.icon.stop()
        host.stop()
        if tray.body._thread.is_alive():
            tray.body.stop()
        panel.stop()


if __name__ == "__main__":
    main()
