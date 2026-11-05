"""Controlled live adapter checks. No owner apps, profiles, credentials or web search.

Run: venv/Scripts/python.exe tasks/probe_browser_automation.py
Both browser modes use the same fulfilled HTTPS fixture, without network access.
"""

import asyncio
import hashlib
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.browser.models import Step
from services.browser.runtime import BrowserControls
from services.browser.worker import ProcessRuntime

HTML = """<!doctype html><title>FRIDAY browser test</title><h1>Controlled fixture</h1>
<label>Search<input id=q></label><button onclick="document.getElementById('result').innerText='Saved test result'">
Save test</button><p id=result>Waiting</p>"""


class FixtureControls(BrowserControls):
    def fixture(self):
        self.context.route("https://example.com/friday-probe", lambda route: route.fulfill(
            status=200, content_type="text/html", body=HTML))
        self.page.goto("https://example.com/friday-probe")
        return self.observe()

    def mutate(self, mode):
        if mode == "value":
            self.page.locator("input").fill("owner change")
        else:
            self.page.locator("input").evaluate("e=>e.outerHTML=e.outerHTML")

    def value(self):
        return self.page.locator("input").input_value()

    def screenshot(self, path):
        self.page.screenshot(path=path)

    def stuck(self):
        time.sleep(60)  # intentionally unresponsive provider, terminated by its owned job


async def check_browser(headless, directory):
    stopped = threading.Event()
    runtime = ProcessRuntime(FixtureControls, (directory,), stopped, browser_tree=True, timeout=20)
    try:
        await runtime.call("start", headless)
        observed = await runtime.call("fixture")
        field = next(c["id"] for c in observed.controls if c["kind"] == "input")
        step = Step(action="fill", target=field, value="test text", reason="Test own fixture")
        _, after = await runtime.call("execute", step, observed.fingerprint())
        assert await runtime.call("value") == "test text"
        await runtime.call("mutate", "value")
        try:
            await runtime.call("execute", step, after.fingerprint())
        except ValueError:
            pass
        else:
            raise AssertionError("Stale value was not blocked")
        assert await runtime.call("value") == "owner change"
        observed = await runtime.call("observe")
        await runtime.call("mutate", "node")
        try:
            await runtime.call("execute", step, observed.fingerprint())
        except ValueError:
            pass
        else:
            raise AssertionError("Replaced node was not blocked")
        observed = await runtime.call("observe")
        button = next(c["id"] for c in observed.controls if c["kind"] == "button")
        _, after = await runtime.call("execute", Step(action="click", target=button,
            reason="Test own fixture"), observed.fingerprint())
        assert "Saved test result" in after.text
        if not headless:
            await runtime.call("screenshot", str(ROOT / "tasks" / "browser-automation-visible.png"))
        return {"mode": "headless" if headless else "visible", "fill_readback": True,
                "stale_value_blocked": True, "replaced_node_blocked": True, "click_observed": True}
    finally:
        stopped.set()
        await runtime.aclose()
        assert not runtime.process.is_alive()


async def check_hung_worker(directory):
    stopped = threading.Event()
    runtime = ProcessRuntime(FixtureControls, (directory,), stopped, browser_tree=True, timeout=.4)
    try:
        runtime.timeout = 20
        await runtime.call("start", True)
        import psutil
        children = psutil.Process(runtime.process.pid).children(recursive=True)
        runtime.timeout = .4
        started = time.monotonic()
        try:
            await runtime.call("stuck")
        except TimeoutError:
            pass
        else:
            raise AssertionError("Hung worker did not time out")
        stopped.set()
        await runtime.aclose()
        assert time.monotonic() - started < 6
        await asyncio.sleep(.2)
        assert not runtime.process.is_alive()
        assert not any(child.is_running() for child in children)
        return {"hung_worker_timeout": True, "owned_browser_tree_exited": True}
    finally:
        if runtime.process.is_alive():
            await runtime.aclose()


async def main():
    with tempfile.TemporaryDirectory(prefix="friday-browser-probe-") as temporary:
        directory = Path(temporary)
        results = [await check_browser(mode, directory) for mode in (True, False)]
        results.append(await check_hung_worker(directory))
    paths = list((ROOT / "services" / "browser").glob("*.py"))
    paths += [ROOT / p for p in ("interfaces/api/routes/chat.py", "interfaces/api/routes/voice.py",
        "interfaces/api/app.py", "interfaces/popup/app.py", "interfaces/popup/computer.py",
        "interfaces/popup/automation.py", "interfaces/tray/backend.py", "providers/policy.py",
        "providers/failover.py", "services/mind/cognition.py", "services/search/web_search.py", "core/config.py")]
    payload = {"results": results, "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                                     for p in paths}}
    output = ROOT / "tasks" / "browser-automation-live.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(results))


if __name__ == "__main__":
    asyncio.run(main())
