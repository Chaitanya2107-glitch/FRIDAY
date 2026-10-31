"""Native proof using only an owned synthetic window; no captured pixels go to disk."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wait(check, seconds=20, reason="Native state did not become ready"):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.15)
    raise RuntimeError(reason)


def api_client():
    import httpx
    from core.config import config
    return httpx.Client(base_url=f"http://{config.API_HOST}:{config.API_PORT}",
                        timeout=httpx.Timeout(30, connect=3), trust_env=False)


def command(client, text):
    response = client.post("/api/v1/chat", json={"message": text, "speak": False})
    response.raise_for_status()
    result = response.json()
    assert result["model"] == "system_control" and result.get("private")
    return result


def reload_desktop():
    import httpx
    import psutil
    import win32con
    import win32gui
    import win32process
    from tasks.restore_command_bar import edit_text
    from services.screen_watch.store import ScreenStore
    launch = ROOT / "interfaces/taskbar/launch.py"
    hwnd = win32gui.FindWindow("FridayQuickBarWindow", None)
    old = None
    ScreenStore().control("pause")
    if hwnd:
        old = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1])
        assert Path(old.cwd()).resolve() == ROOT
        assert any(Path(arg).is_absolute() and Path(arg).resolve() == launch for arg in old.cmdline()[1:])
        edit = win32gui.FindWindowEx(hwnd, 0, "Edit", None)
        draft = edit and edit_text(edit) and not win32gui.GetWindowLong(edit, win32con.GWL_STYLE) & 0x800
        assert not (win32gui.GetForegroundWindow() == hwnd and draft), "Friday has a focused draft."
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        old.wait(timeout=40)
    subprocess.Popen([str(ROOT / "venv/Scripts/pythonw.exe"), "-B", str(launch)], cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    def reopened():
        window = win32gui.FindWindow("FridayQuickBarWindow", None)
        return window if window and (not old or win32process.GetWindowThreadProcessId(window)[1] != old.pid) else None
    hwnd = wait(reopened, 50, "Friday did not reopen")
    with api_client() as client:
        def ready():
            try:
                return client.get("/health").status_code == 200
            except httpx.HTTPError:
                return False
        wait(ready, 60, "Friday's backend did not become ready")
    return {"previous_pid": old.pid if old else None,
            "desktop_pid": win32process.GetWindowThreadProcessId(hwnd)[1]}


def build_fixture():
    output = ROOT / "tasks/screen-native"
    output.mkdir(exist_ok=True)
    target = output / "FridayScreenFixture.exe"
    compiler = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
    assert compiler.is_file()
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/out:" + str(target),
                    "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                    str(ROOT / "tasks/fixtures/ScreenWatchFixture.cs")], check=True, cwd=ROOT,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    return subprocess.Popen([str(target)], cwd=ROOT)


def focus_fixture(hwnd):
    """Windows may deny background SetForegroundWindow; click only our known form."""
    import win32api
    import win32con
    import win32gui
    import win32process
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    bounds = win32api.GetMonitorInfo(win32api.MonitorFromPoint((0, 0), win32con.MONITOR_DEFAULTTOPRIMARY))["Work"]
    width, height = min(1095, bounds[2] - bounds[0] - 40), min(649, bounds[3] - bounds[1] - 40)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, bounds[0] + 20, bounds[1] + 20, width, height,
                          win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)
    time.sleep(.2)
    cursor = win32gui.GetCursorPos()
    try:
        point = win32gui.ClientToScreen(hwnd, (45, 135))
        at_point = win32gui.WindowFromPoint(point)
        assert at_point and win32process.GetWindowThreadProcessId(at_point)[1] == win32process.GetWindowThreadProcessId(hwnd)[1], "The owned fixture is covered; no mouse click sent."
        win32api.SetCursorPos(point)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    finally:
        win32api.SetCursorPos(cursor)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except win32gui.error:
        pass
    if win32gui.GetForegroundWindow() != hwnd:
        import psutil
        import win32process
        point = win32gui.ClientToScreen(hwnd, (45, 135))
        at_point = win32gui.WindowFromPoint(point)
        current = win32gui.GetForegroundWindow()
        print(json.dumps({"focus_diagnostic": {
            "owned_title": win32gui.GetWindowText(hwnd) == "Graph lecture fixture - Friday screen test",
            "fixture_rect": win32gui.GetWindowRect(hwnd), "click_point": point,
            "point_belongs_to_fixture": win32process.GetWindowThreadProcessId(at_point)[1] == win32process.GetWindowThreadProcessId(hwnd)[1],
            "foreground_app": capture_app(current)
        }}), flush=True)
    wait(lambda: win32gui.GetForegroundWindow() == hwnd, 3, "The owned fixture did not receive focus")


def capture_app(hwnd):
    import psutil
    import win32process
    try:
        return psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name() if hwnd else None
    except (psutil.Error, ValueError):
        return None


def diagnostic_reader(stopped):
    from services.screen_watch.capture import ScreenReader
    class Reader(ScreenReader):
        def read(self, *args):
            try:
                return super().read(*args)
            except Exception as error:
                # This reader is used only with the positively identified fixture.
                import traceback
                (ROOT / "tasks/screen-native-fixture-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                if sys.stdout is not None:
                    print("Owned fixture UIA error: " + type(error).__name__ + ": " + str(error), flush=True)
                raise
    return Reader(stopped)


def probe(reload=True):
    import ctypes
    import psutil
    import win32api
    import win32con
    import win32gui
    import win32process
    from interfaces.popup.win32 import WM_APP_SHOW
    from services.screen_watch import capture
    from services.screen_watch import create_reader
    from services.screen_watch.store import ScreenStore
    from services.browser.worker import ProcessRuntime
    from tasks.restore_command_bar import edit_text
    from tasks.verify_screen_awareness import identity, policy

    ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    policy()
    desktop = reload_desktop() if reload else {"desktop_pid": win32process.GetWindowThreadProcessId(
        win32gui.FindWindow("FridayQuickBarWindow", None))[1]}
    result = {"source_identity": identity(), **desktop,
              "synthetic_window_only": True, "captured_images_saved": False}
    fixture = build_fixture()
    store = ScreenStore()
    original = win32gui.GetForegroundWindow()
    try:
        def own_window():
            found = []
            win32gui.EnumWindows(lambda hwnd, _: found.append(hwnd) if
                win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] == fixture.pid
                and win32gui.GetWindowText(hwnd) == "Graph lecture fixture - Friday screen test" else None, None)
            return found[0] if found else None
        hwnd = wait(own_window)
        assert psutil.Process(fixture.pid).exe().lower().endswith("fridayscreenfixture.exe")
        focus_fixture(hwnd)
        with api_client() as client:
            status = client.get("/api/v1/system/status")
            status.raise_for_status()
            assert "screen_watch" in status.json(), "The desktop is connected to an older backend."
            command(client, "start screen awareness")
            badge = wait(lambda: capture.indicator(win32gui.FindWindow(None, capture.BADGE_TITLE)), 25,
                         "The actual visible badge was not accepted")
            result["native_badge_accepted"] = True
            print("Native watching badge accepted", flush=True)
            window = capture.foreground()
            print(json.dumps({"post_badge_focus": {"app": window["app"] if window else None,
                "fixture": bool(window and window["scope"]["pid"] == fixture.pid),
                "badge": bool(window and window["scope"]["hwnd"] == badge["hwnd"])}}), flush=True)
            focus_fixture(hwnd)
            async def preflight():
                stopped = threading.Event()
                reader = ProcessRuntime(diagnostic_reader, (), stopped, timeout=8)
                try:
                    window = capture.foreground()
                    assert window["scope"]["pid"] == fixture.pid
                    return await reader.call("read", window, badge)
                finally:
                    stopped.set()
                    await reader.aclose()
            frame = asyncio.run(preflight())
            print(json.dumps({"owned_fixture_read": {"blocked": frame.get("blocked"),
                                                      "text_length": len(frame.get("text", ""))}}), flush=True)
            assert not frame.get("blocked") and len(frame.get("text", "")) >= 80
            def epoch():
                response = client.get("/api/v1/system/status")
                response.raise_for_status()
                return response.json()["screen_watch"]["epoch"]
            def observation(source, expected_epoch):
                with store.db() as conn:
                    row = conn.execute("SELECT * FROM screen_observations WHERE app=? AND source=? AND epoch=? "
                                       "ORDER BY id DESC LIMIT 1", ("fridayscreenfixture", source, expected_epoch)).fetchone()
                    return dict(row) if row else None
            started = time.monotonic()
            expected = epoch()
            row = wait(lambda: observation("accessible_text", expected), 90, "Text-first observation did not finish")
            assert "graph" in (row["summary"] + row["activity"]).lower()
            result["text_first_seconds"] = round(time.monotonic() - started, 3)
            print("Native text-first interpretation saved", flush=True)

            # Exercise the real Enter / restore focus / private reply path.
            bar = win32gui.FindWindow("FridayQuickBarWindow", None)
            win32gui.SendMessage(bar, WM_APP_SHOW, 0, 0)
            edit = win32gui.FindWindowEx(bar, 0, "Edit", None)
            win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, "what am I doing")
            win32gui.SendMessage(edit, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
            reply = wait(lambda: edit_text(edit) if "Last screen check" in edit_text(edit) else None, 25,
                         "The native command bar did not return a fresh screen interpretation")
            assert "graph" in reply.lower()
            result["native_private_screen_reply"] = True
            print("Native command-bar screen reply verified", flush=True)
            win32gui.ShowWindow(bar, win32con.SW_HIDE)

            command(client, "pause screen awareness")
            win32gui.SendMessage(hwnd, 0x8001, 0, 0)  # image-only subject matter
            focus_fixture(hwnd)
            command(client, "resume screen awareness")
            expected = epoch()
            started = time.monotonic()
            row = wait(lambda: observation("vision", expected), 100, "Active-window vision observation did not finish")
            assert "graph" in (row["summary"] + row["activity"]).lower()
            result["active_window_vision_seconds"] = round(time.monotonic() - started, 3)
            print("Native active-window vision interpretation saved", flush=True)

            # Verify an actual UIA protected field suppresses the whole frame.
            win32gui.SendMessage(hwnd, 0x8002, 0, 0)
            time.sleep(.3)
            expected_window = capture.foreground()
            assert expected_window["scope"]["pid"] == fixture.pid
            async def protected_read():
                stopped = threading.Event()
                reader = ProcessRuntime(create_reader, (), stopped, timeout=8)
                try:
                    return await reader.call("image", expected_window, badge)
                finally:
                    stopped.set()
                    await reader.aclose()
            assert asyncio.run(protected_read()) == {"blocked": "private_window"}
            result["native_protected_field_blocks_image"] = True

            # Click the real pause button, without taking focus from the fixture.
            badge_hwnd = badge["hwnd"]
            rect, cursor = win32gui.GetWindowRect(badge_hwnd), win32gui.GetCursorPos()
            try:
                win32api.SetCursorPos(((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
            finally:
                win32api.SetCursorPos(cursor)
            wait(lambda: not win32gui.IsWindowVisible(badge_hwnd), 3, "Pause badge did not hide immediately")
            wait(lambda: store.settings()["paused"], 8, "Native pause did not reach the backend")
            result["native_pause_button"] = True
    finally:
        store.control("pause")
        store.forget("fridayscreenfixture")
        if fixture.poll() is None:
            windows = []
            win32gui.EnumWindows(lambda hwnd, _: windows.append(hwnd) if
                win32process.GetWindowThreadProcessId(hwnd)[1] == fixture.pid else None, None)
            for hwnd in windows:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            fixture.wait(timeout=10)
        if original and win32gui.IsWindow(original):
            try:
                win32gui.SetForegroundWindow(original)
            except win32gui.error:
                pass
    (ROOT / "tasks/screen-native-proof.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    if "--worker-only" in sys.argv:
        from tasks.native_screen_diagnostics import worker_state
        print(json.dumps(asyncio.run(worker_state())), flush=True)
    elif "--diagnose" in sys.argv:
        from tasks.native_screen_diagnostics import diagnose
        diagnose()
    else:
        probe(reload="--no-reload" not in sys.argv)
