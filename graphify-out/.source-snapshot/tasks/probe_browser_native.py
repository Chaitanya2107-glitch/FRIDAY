"""Live pywinauto checks against our disposable fixture, never an owner application."""

import asyncio
import json
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.browser.models import Step
from services.browser.windows import WindowsRuntime


async def main():
    import win32con
    import win32gui
    process = subprocess.Popen([sys.executable, str(ROOT / "tasks" / "browser_native_fixture.py")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    window, runtime = None, WindowsRuntime(threading.Event())
    try:
        line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 10)
        if not line:
            raise RuntimeError(process.stderr.read())
        window = json.loads(line)["hwnd"]
        observation = await runtime.call("start", False)
        assert observation.location == str(window), observation.title
        field = next(c["id"] for c in observation.controls if c["kind"] == "Edit" and c["automation_id"] == "1148")
        _, after = await runtime.call("execute", Step(action="fill", target=field,
            value="fixture-not-a-real-save.txt", reason="Test literal field entry"), observation.fingerprint())
        assert "fixture-not-a-real-save.txt" in after.text
        button = next(c["id"] for c in after.controls if c["kind"] == "Button" and c["name"] == "Save")
        _, after = await runtime.call("execute", Step(action="click", target=button,
            reason="Invoke disposable fixture button"), after.fingerprint())
        assert "Fixture button invoked" in after.text
        result = {"native_control_readback": True, "literal_fill_verified": True,
                  "invoke_result_observed": True, "target": "disposable fixture only"}
        (ROOT / "tasks" / "browser-automation-native.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
    finally:
        runtime.stopped.set()
        await runtime.aclose()
        if window and win32gui.IsWindow(window):
            win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
        try:
            await asyncio.wait_for(asyncio.to_thread(process.wait), 3)
        except TimeoutError:
            process.terminate()


if __name__ == "__main__":
    asyncio.run(main())
