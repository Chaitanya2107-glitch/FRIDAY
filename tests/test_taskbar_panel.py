"""Opt-in native GUI smoke test using isolated data and mocked microphone calls."""

import os
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import ImageGrab
import pytest
import win32con
import win32gui

from interfaces.taskbar.panel import ControlPanel
from interfaces.tray import backend, tray as tray_module

pytestmark = pytest.mark.skipif(os.environ.get("FRIDAY_PANEL_UI_TEST") != "1",
                                reason="Native GUI check requires an interactive desktop")


def test_native_panel_controls_and_menu(tmp_path, monkeypatch):
    import faulthandler
    import tkinter as tk
    faulthandler.dump_traceback_later(25)
    events = []
    monkeypatch.setattr(backend, "settings", backend.Settings())
    api = SimpleNamespace(settings=backend.settings, stop_listening=lambda **kw: events.append("mic-stop"),
                          stop_wake=lambda session: events.append("wake-stop"), BackendError=backend.BackendError)
    monkeypatch.setattr(tray_module, "_in_background", lambda action, *args: action(*args))
    tray = tray_module.FridayTray(lambda: events.append("bar"), lambda: events.append("quit"),
                                 lambda *args: False, api=api)
    tray.online, tray.default_provider = True, "ollama"
    tray.runtime_status = {"mode": {"name": "normal"}}
    runtime = SimpleNamespace(owned=True, busy=False, message="Ready", operate=events.append)
    bar = SimpleNamespace(request_show=lambda: events.append("bar"), request_quit=lambda: events.append("quit"))
    panel = ControlPanel(tray, runtime, bar)
    try:
        print("Building synthetic panel", flush=True)
        panel._build()
        print("Checking panel state", flush=True)
        panel._tick()
        panel.root.update()
        assert panel.root.state() == "withdrawn"
        panel.show((1305, 1020, 1480, 1080))
        panel.root.update()
        style = win32gui.GetWindowLong(panel._hwnd, win32con.GWL_EXSTYLE)
        assert style & win32con.WS_EX_TOOLWINDOW
        assert not style & win32con.WS_EX_APPWINDOW
        assert panel.root.overrideredirect()
        assert "Ready" in panel.status["text"]
        assert panel.buttons["start"]["state"] == "disabled"
        assert panel.buttons["restart"]["state"] == "normal"
        panel.buttons["speech"].invoke()
        panel._tick()
        assert panel.buttons["speech"]["text"].endswith("Off")
        # Native popup menus wait for a user selection on Windows. Check their
        # actual entries without leaving this unattended check inside that wait.
        monkeypatch.setattr(tk.Menu, "tk_popup", lambda *args: None)
        panel._more_controls()
        panel.root.update()
        assert panel._menu.index("end") > 10
        panel._menu.unpost()
        panel._menu.grab_release()
        tray.wake_on = tray.in_conversation = api.settings.conversation = True
        tray._wake_session = "synthetic"
        tray.pause_microphone(wait=True)
        panel._tick()
        assert events[-2:] == ["wake-stop", "mic-stop"]
        assert panel.buttons["wake"]["text"].endswith("Off")
        panel.root.update()
        panel.show((1305, 1020, 1480, 1080))
        panel._dismiss_after = time.monotonic() + 5
        panel.root.update()
        time.sleep(.25)
        panel.root.update()
        x, y = panel.root.winfo_rootx(), panel.root.winfo_rooty()
        w, h = panel.root.winfo_width(), panel.root.winfo_height()
        assert 370 <= w < 800 and 300 < h < panel.root.winfo_screenheight() - 90
        screenshot = Path(__file__).resolve().parents[1] / "tasks/widget-flyout-preview.png"
        preview = ImageGrab.grab(bbox=(x, y, x + w, y + h)).convert("RGB")
        assert dict((color, count) for count, color in preview.getcolors(w * h)).get((16, 20, 19), 0) > w * h * .2
        preview.save(screenshot)
        print(f"Panel preview: {screenshot}")
        tray.online = runtime.owned = False
        runtime.message = "Stopped"
        panel._tick()
        assert panel.buttons["start"]["state"] == "normal"
        assert panel.buttons["listen"]["state"] == "disabled"
        panel.show()
        panel._dismiss_after = 0
        with monkeypatch.context() as context:
            context.setattr(win32gui, "GetForegroundWindow", lambda: 1234)
            context.setattr(win32gui, "IsChild", lambda *args: False)
            context.setattr(win32gui, "GetClassName", lambda hwnd: "Shell_TrayWnd")
            context.setattr(win32gui, "GetCursorPos", lambda: (1400, 1050))
            assert not panel._outside()  # Mouse-down activates the taskbar before release toggles.
            context.setattr(win32gui, "GetClassName", lambda hwnd: "OtherApp")
            panel._menu_open = True
            assert not panel._outside()
            panel._menu_open = False
            assert panel._outside()
            panel._tick()
        assert panel.root.state() == "withdrawn"
        def start_from_click(action):
            events.append(action)
            tray.online = runtime.owned = True
        monkeypatch.setattr(panel, "_lifecycle", start_from_click)
        assert "start" not in events
        panel.request_toggle((1305, 1020, 1480, 1080))
        panel._tick()
        assert panel._visible and events.count("start") == 1
        panel.request_toggle()
        panel._tick()
        assert not panel._visible
        panel.request_toggle()
        panel._tick()
        assert panel._visible and events.count("start") == 1
        panel.show()
        panel.buttons["close"].invoke()
        panel.root.update()
        assert panel.root.state() == "withdrawn"
    finally:
        faulthandler.cancel_dump_traceback_later()
        if hasattr(panel, "root"):
            panel.root.destroy()
        panel.buttons.clear()
        for key in ("_photo", "_menu_variables", "_menu", "status", "detail"):
            panel.__dict__.pop(key, None)
        panel.root = None
        tray.icon.stop()


def test_panel_and_body_use_their_own_tk_threads(tmp_path, monkeypatch, caplog):
    from interfaces.body import window as body_module
    monkeypatch.setattr(body_module, "state_path", tmp_path / "body.json")
    monkeypatch.setattr(body_module.sounds, "ensure", lambda *args: {})
    monkeypatch.setattr(body_module.sounds, "play", lambda *args: None)
    monkeypatch.setattr(body_module.sensors, "InputCounter", lambda: SimpleNamespace(
        start=lambda: None, take=lambda: (0, 0), last_key=0))
    monkeypatch.setattr(body_module.sensors, "fullscreen", lambda: False)
    api = SimpleNamespace(settings=backend.settings, body_state=lambda since: {"events": [], "last": 0})
    bar = SimpleNamespace(request_show=lambda: None, request_quit=lambda: None)
    tray = tray_module.FridayTray(bar.request_show, bar.request_quit, lambda *args: False, api=api)
    tray.online = True
    runtime = SimpleNamespace(owned=False, busy=False, message="Synthetic preview")
    panel = ControlPanel(tray, runtime, bar)
    body = body_module.FridayBody(tray, bar, api=api)
    tray.body = body
    try:
        panel.start()
        deadline = time.monotonic() + 5
        while getattr(body, "_last_pose", None) is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert getattr(body, "_last_pose", None) is not None
    finally:
        body.stop(wait=5)
        panel.stop()
        tray.icon.stop()
    assert not body._thread.is_alive() and not panel._thread.is_alive()
    assert not hasattr(body, "_root") and panel.root is None
    assert "body stopped" not in caplog.text and "body frame failed" not in caplog.text


def test_taskbar_child_button_remains_when_backend_is_stopped(monkeypatch, caplog):
    from interfaces.taskbar import host as host_module
    monkeypatch.setattr(host_module, "HOST_CLASS", "FridayWidgetNativeTestHost")
    monkeypatch.setattr(host_module, "BUTTON_CLASS", "FridayWidgetNativeTestButton")
    state, clicks, shows = {"status": "offline"}, [], []
    host = host_module.TaskbarButton(clicks.append, state=lambda: state["status"], show=shows.append)

    def wait(check):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.05)
        pytest.fail("Native taskbar widget did not reach the expected state")

    try:
        host.start()
        print("Native layout:", host_module.taskbar_layout(), flush=True)
        wait(lambda: host.button)
        native_taskbar = win32gui.FindWindow("Shell_TrayWnd", None)
        assert win32gui.GetParent(host.button) == native_taskbar
        assert win32gui.GetWindowLong(host.button, win32con.GWL_STYLE) & win32con.WS_CHILD
        assert win32gui.GetWindowLong(host.button, win32con.GWL_EXSTYLE) & win32con.WS_EX_LAYERED
        assert not win32gui.IsWindowVisible(host.hwnd)
        # WM_PRINTCLIENT alone also paints windows that DWM never shows. Check
        # the real desktop pixels after revealing the user's auto-hidden bar.
        import win32api
        cursor = win32gui.GetCursorPos()
        try:
            monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(native_taskbar))["Monitor"]
            rect = win32gui.GetWindowRect(host.button)
            win32api.SetCursorPos(((rect[0] + rect[2]) // 2, monitor[3] - 1))
            time.sleep(.25)
            if win32gui.GetWindowRect(host.button)[3] > monitor[3]:
                for key, flags in ((win32con.VK_LWIN, 0), (ord("T"), 0),
                                   (ord("T"), win32con.KEYEVENTF_KEYUP), (win32con.VK_LWIN, win32con.KEYEVENTF_KEYUP)):
                    win32api.keybd_event(key, 0, flags, 0)
            wait(lambda: win32gui.GetWindowRect(host.button)[3] <= monitor[3])
            time.sleep(.4)
            screen_rect = win32gui.GetWindowRect(host.button)
            actual = ImageGrab.grab(bbox=screen_rect).convert("RGB")
            colors = {color: count for count, color in actual.getcolors(actual.width * actual.height)}
            fill = colors.get((37, 44, 36), 0) + colors.get((49, 59, 48), 0)
            assert fill > actual.width * actual.height * .35, "Taskbar child exists but is not drawn on screen"
            actual.save(Path(__file__).resolve().parents[1] / "tasks/widget-onscreen-preview.png")
        finally:
            win32api.SetCursorPos(cursor)
        import win32ui
        from PIL import Image
        source = win32gui.GetDC(0)
        screen = win32ui.CreateDCFromHandle(source)
        memory = screen.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        width, height = win32gui.GetClientRect(host.button)[2:]
        bitmap.CreateCompatibleBitmap(screen, width, height)
        old = memory.SelectObject(bitmap)
        try:
            win32gui.SendMessage(host.button, 0x0318, memory.GetSafeHdc(), 0)
            pixels = bitmap.GetBitmapBits(True)
            preview = Image.frombuffer("RGB", (width, height), pixels, "raw", "BGRX", 0, 1)
            preview.save(Path(__file__).resolve().parents[1] / "tasks/widget-button-preview.png")
            assert "callback failed" not in caplog.text
        finally:
            memory.SelectObject(old)
            win32gui.DeleteObject(bitmap.GetHandle())
            memory.DeleteDC()
            screen.DeleteDC()
            win32gui.ReleaseDC(0, source)
        win32gui.PostMessage(host.button, win32con.WM_LBUTTONUP, 0, 0)
        wait(lambda: len(clicks) == 1)
        assert clicks[0][::2] == win32gui.GetWindowRect(host.button)[::2]
        assert clicks[0][3] - clicks[0][1] == height
        win32gui.PostMessage(host.hwnd, host_module.ACTIVATE, 1, 0)
        win32gui.PostMessage(host.hwnd, host_module.ACTIVATE, 1, 0)
        wait(lambda: len(shows) == 2)
        assert all(rect[::2] == clicks[0][::2] and rect[3] - rect[1] == height for rect in shows)
        assert len(clicks) == 1  # Auto-hide may animate the anchor vertically between messages.
        state["status"] = "online"
        wait(lambda: win32gui.GetWindowText(host.button).endswith("Ready"))
        state["status"] = "offline"
        wait(lambda: win32gui.GetWindowText(host.button).endswith("Offline"))
        assert win32gui.IsWindow(host.button) and host._thread.is_alive()
    finally:
        host.stop()
    assert not host._thread.is_alive()


def test_widget_recovers_after_lost_space_and_parent_replacement(monkeypatch, caplog):
    import win32api
    from interfaces.taskbar import host as host_module
    monkeypatch.setattr(host_module, "HOST_CLASS", "FridayWidgetRecoveryHost")
    monkeypatch.setattr(host_module, "BUTTON_CLASS", "FridayWidgetRecoveryButton")
    instance = win32api.GetModuleHandle(None)
    wc = win32gui.WNDCLASS()
    wc.hInstance, wc.lpszClassName = instance, "FridayFakeTaskbarForRecovery"
    wc.lpfnWndProc = win32gui.DefWindowProc
    win32gui.RegisterClass(wc)
    parents = []

    def parent():
        hwnd = win32gui.CreateWindowEx(0, wc.lpszClassName, "Test only", win32con.WS_POPUP,
                                      0, 0, 1600, 60, 0, 0, instance, None)
        parents.append(hwnd)
        return hwnd

    layout = {"parent": parent(), "slot": (100, 5, 240, 55), "missing": False}
    monkeypatch.setattr(host_module, "taskbar_layout", lambda: None if layout["missing"] else (
        layout["parent"], (0, 0, 1600, 60), layout["slot"], 96))
    host = host_module.TaskbarButton(lambda anchor: None)

    def wait(check):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.05)
        pytest.fail("Widget did not recover its synthetic parent")

    def visible_style():
        return bool(host.button and win32gui.GetWindowLong(host.button, win32con.GWL_STYLE) & win32con.WS_VISIBLE)

    try:
        host.start()
        wait(visible_style)
        layout["slot"] = None
        wait(lambda: not visible_style())
        assert host._thread.is_alive()
        layout["slot"] = (100, 5, 240, 55)
        wait(visible_style)
        layout["missing"] = True
        wait(lambda: not visible_style())
        layout["missing"] = False
        previous = layout["parent"]
        layout["parent"] = parent()
        win32gui.DestroyWindow(previous)
        wait(lambda: visible_style() and win32gui.GetParent(host.button) == layout["parent"])
        host.report_errors()
        assert host._thread.is_alive() and "callback failed" not in caplog.text
    finally:
        host.stop()
        for hwnd in parents:
            if win32gui.IsWindow(hwnd):
                win32gui.DestroyWindow(hwnd)
        win32gui.UnregisterClass(wc.lpszClassName, instance)
    assert not host._thread.is_alive()
