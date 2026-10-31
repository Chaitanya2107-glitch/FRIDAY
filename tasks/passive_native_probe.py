"""Prove automatic learning before ordinary conversation, with owned test content."""
import ctypes
import json
from pathlib import Path
import sys
import threading
import time
import asyncio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def probe(reload=True):
    import win32api
    import win32con
    import win32gui
    import win32process
    from interfaces.popup.win32 import WM_APP_SHOW
    from services.browser.worker import ProcessRuntime
    from services.screen_watch import capture, create_reader
    from services.screen_watch.store import ScreenStore
    from tasks.restore_command_bar import edit_text
    from tasks.screen_native_probe import api_client, build_fixture, command, focus_fixture, reload_desktop, wait
    from tasks.verify_passive_assistant import identity, policy, production_identity, write

    ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    policy()
    desktop = reload_desktop() if reload else {"desktop_pid": win32process.GetWindowThreadProcessId(
        win32gui.FindWindow("FridayQuickBarWindow", None))[1]}
    result = {"source_identity": identity(), "production_identity": production_identity(), **desktop,
              "synthetic_window_only": True, "captured_images_saved": False}
    fixture = build_fixture()
    store = ScreenStore()
    original = win32gui.GetForegroundWindow()
    try:
        def own_window():
            found = []
            win32gui.EnumWindows(lambda hwnd, _: found.append(hwnd) if win32gui.IsWindowVisible(hwnd)
                and win32process.GetWindowThreadProcessId(hwnd)[1] == fixture.pid
                and win32gui.GetWindowText(hwnd) == "Graph lecture fixture - Friday screen test" else None, None)
            return found[0] if found else None
        hwnd = wait(own_window)
        focus_fixture(hwnd)
        with api_client() as client:
            client.timeout = 65
            command(client, "start screen awareness")
            epoch = store.settings()["epoch"]
            badge = wait(lambda: capture.indicator(win32gui.FindWindow(None, capture.BADGE_TITLE)), 25,
                         "The native watching badge was not accepted")
            focus_fixture(hwnd)
            result["native_badge_accepted"] = True
            diagnostics_at = [0.0]
            def learned(source):
                with store.db() as conn:
                    row = conn.execute("SELECT * FROM screen_observations WHERE app=? AND source=? AND epoch=? "
                        "ORDER BY id DESC LIMIT 1", ("fridayscreenfixture", source, epoch)).fetchone()
                    if not row:
                        if time.monotonic() >= diagnostics_at[0]:
                            diagnostics_at[0] = time.monotonic() + 5
                            foreground = capture.foreground()
                            state = client.get("/api/v1/system/status").json()["screen_watch"]
                            print(json.dumps({"learning_progress": {"state": state["state"], "source": source,
                                "fixture_foreground": bool(foreground and foreground["scope"]["pid"] == fixture.pid)}}), flush=True)
                        return None
                    day = conn.execute("SELECT * FROM screen_activity_days WHERE app=? AND subject=? AND kind=?",
                        ("fridayscreenfixture", row["subject"].lower(), row["kind"])).fetchone()
                    return dict(row) if day else None
            started = time.monotonic()
            row = wait(lambda: learned("accessible_text"), 90, "Background learning did not finish")
            assert "graph" in row["subject"].lower() and row["kind"] in {"reading", "watching"}
            result["learned_before_any_activity_question"] = True
            result["passive_text_seconds"] = round(time.monotonic() - started, 3)
            print("Automatic topic learning committed before any activity question", flush=True)

            # This is ordinary conversation, not a screen-report command.
            started = time.monotonic()
            reply = client.post("/api/v1/chat", json={"message": "Give me one small suggestion for the topic I was just viewing.",
                                                    "speak": False})
            reply.raise_for_status()
            data = reply.json()
            print(json.dumps({"ordinary_reply_metadata": {k: data.get(k) for k in
                ("private", "provider", "model", "action_success", "tokens_used")}}), flush=True)
            assert data["private"] and data["provider"] == "ollama" and data["model"] != "system_control"
            assert "graph" in data["response"].lower()
            result["ordinary_contextual_reply"] = True
            result["ordinary_reply_seconds"] = round(time.monotonic() - started, 3)
            print("Ordinary local conversation used the automatically learned topic", flush=True)

            bar = win32gui.FindWindow("FridayQuickBarWindow", None)
            edit = win32gui.FindWindowEx(bar, 0, "Edit", None)
            def submit(message):
                win32gui.SendMessage(bar, WM_APP_SHOW, 0, 0)
                win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, message)
                win32gui.SendMessage(edit, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
                def answered():
                    value = edit_text(edit)
                    return value if value and value != message and not value.startswith("Sending") else None
                return wait(answered, 60, "The native ordinary reply stayed on Sending")
            reply = submit("Give me a short suggestion for that same topic.")
            assert "graph" in reply.lower()
            assert win32gui.IsWindowVisible(bar)
            time.sleep(3.2)  # beyond the short command-confirmation timer
            assert win32gui.IsWindowVisible(bar) and edit_text(edit) == reply
            result["native_ordinary_reply_readable"] = True
            reply = submit("Name that topic in one short phrase.")
            assert "graph" in reply.lower()
            result["native_followup_uses_private_thread"] = True
            win32gui.ShowWindow(bar, win32con.SW_HIDE)
            print("Native ordinary reply and contextual follow-up verified", flush=True)

            command(client, "pause screen awareness")
            win32gui.SendMessage(hwnd, 0x8001, 0, 0)
            focus_fixture(hwnd)
            command(client, "resume screen awareness")
            epoch = store.settings()["epoch"]
            row = wait(lambda: learned("vision"), 100, "Background vision learning did not finish")
            assert "graph" in row["subject"].lower()
            result["native_vision_updates_learning"] = True
            win32gui.SendMessage(hwnd, 0x8002, 0, 0)
            time.sleep(.3)
            window = capture.foreground()
            assert window["scope"]["pid"] == fixture.pid
            async def protected_read():
                stopped = threading.Event()
                reader = ProcessRuntime(create_reader, (), stopped, timeout=8)
                try:
                    return await reader.call("image", window, badge)
                finally:
                    stopped.set()
                    await reader.aclose()
            assert asyncio.run(protected_read()) == {"blocked": "private_window"}
            result["native_protected_field_blocks_image"] = True
            rect, cursor = win32gui.GetWindowRect(badge["hwnd"]), win32gui.GetCursorPos()
            try:
                win32api.SetCursorPos(((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
            finally:
                win32api.SetCursorPos(cursor)
            wait(lambda: store.settings()["paused"], 8, "Native Pause did not reach the backend")
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
    write("passive-native-proof.json", result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    probe(reload="--no-reload" not in sys.argv)
