import asyncio
import json
import socket
import threading
from types import SimpleNamespace

import httpx
import pytest

from core.config import config
from services.browser import commands, models, research, safety, service
from services.browser.commands import Command
from services.browser.models import Observation, Step


@pytest.mark.parametrize("text,kind,headless,task", [
    ("browser task open https://example.com", "browser", False, "open https://example.com"),
    ("\\b headless compare laptops", "browser", True, "compare laptops"),
    ("Friday, research headless robot control", "research", True, "robot control"),
    ("please deep research robot control", "research", False, "robot control"),
    ("desktop task type hello in Notepad", "desktop", False, "type hello in Notepad"),
    ("research headless browsers", "research", True, "browsers"),
    ("research browser headless detection", "research", False, "browser headless detection"),
    ("browser yes", "yes", False, ""),
    ("\\b status", "status", False, ""),
    ("stop the browser task", "stop", False, ""),
    ("research report", "report", False, ""),
])
def test_explicit_commands(text, kind, headless, task):
    assert commands.match_command(text) == Command(kind, task, headless)


@pytest.mark.parametrize("text", ["what is browser automation?", "don't research robots", "note research robotics",
                                      '"browser task send a message"', "open chrome", "researching robotics", "yes"])
def test_discussion_and_other_commands_never_start_automation(text):
    assert commands.match_command(text) is None


def dns(host, *args, **kwargs):
    address = "127.0.0.1" if host in {"localhost", "internal.example"} else "93.184.216.34"
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]


@pytest.mark.parametrize("url", ["file:///C:/secret", "javascript:alert(1)", "http://localhost", "http://internal.example",
                                      "https://user:pass@example.com", "https://example.com:8000",
                                      "https://example.com/with space", "https://example.com\\@evil.com"])
def test_public_url_boundary(monkeypatch, url):
    monkeypatch.setattr(safety.socket, "getaddrinfo", dns)
    with pytest.raises(ValueError):
        safety.public_url(url)


def test_url_normalization_and_extraction(monkeypatch):
    monkeypatch.setattr(safety.socket, "getaddrinfo", dns)
    assert safety.public_url("https://example.com#part") == "https://example.com/"
    title, text = safety.extract_html("""<html><title>Evidence</title><body><nav>navigation</nav>
      <script>malicious()</script><style>hidden</style><p hidden>secret</p>
      <p aria-hidden='true'>invisible</p><template>template</template><p>Visible evidence.</p></body></html>""",
                                     "https://example.com")
    assert title == "Evidence" and text.strip() == "Visible evidence."


def mock_http(monkeypatch, responder):
    original = httpx.Client
    monkeypatch.setattr(safety.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(responder), **kwargs))
    monkeypatch.setattr(safety.socket, "getaddrinfo", dns)


def test_redirect_to_private_target_is_blocked_before_request(monkeypatch, tmp_path):
    seen = []
    def respond(request):
        seen.append(request.url.host)
        return httpx.Response(302, headers={"location": "http://internal.example/private"})
    mock_http(monkeypatch, respond)
    with pytest.raises(ValueError):
        safety.download_file("https://example.com", tmp_path, threading.Event())
    assert seen == ["example.com"]


def test_download_cap_and_cancellation_leave_no_file(monkeypatch, tmp_path):
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=b"too large"))
    monkeypatch.setattr(safety, "MAX_DOWNLOAD_BYTES", 2)
    with pytest.raises(ValueError):
        safety.download_file("https://example.com/file.exe", tmp_path, threading.Event())
    assert list(tmp_path.iterdir()) == []
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(InterruptedError):
        safety.download_file("https://example.com/file.exe", tmp_path, stopped)
    assert list(tmp_path.iterdir()) == []


def test_download_receipt_is_bound_to_saved_bytes(monkeypatch, tmp_path):
    import hashlib
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=b"download content"))
    path, size, digest = safety.download_file("https://example.com/file.txt", tmp_path, threading.Event())
    assert path.parent == tmp_path and path.read_bytes() == b"download content"
    assert size == 16 and digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_browser_download_uses_resolved_link_including_html_base(monkeypatch, tmp_path):
    from services.browser import runtime
    received = []
    def download(url, directory, stopped):
        received.append(url)
        return directory / "package.exe", 3, "digest"
    monkeypatch.setattr(runtime, "download_file", download)
    browser = runtime.BrowserControls(threading.Event(), tmp_path)
    target = SimpleNamespace(evaluate=lambda script: "https://cdn.example.com/assets/package.exe")
    assert "3 bytes" in browser._download(target)
    assert received == ["https://cdn.example.com/assets/package.exe"]


OBS = Observation("https://example.com/", "Example", "Task result is visible.",
                  [{"id": 1, "kind": "input", "name": "Search", "protected": False}])


@pytest.mark.parametrize("payload", [
    {"action": "evaluate", "reason": "run JS", "value": "alert(1)"},
    {"action": "click", "reason": "click", "target": 99},
    {"action": "press", "reason": "type code", "target": 1, "value": "ctrl+r"},
    {"action": "done", "reason": "finished", "value": "invented evidence"},
    {"action": "fill", "reason": "type", "target": True, "value": "hello"},
    {"action": "click", "reason": "click", "target": 1, "script": "evil"},
])
def test_generated_actions_are_closed_and_evidence_checked(payload):
    with pytest.raises(ValueError):
        models.parse_step(json.dumps(payload), OBS, "browser")


class FakeRuntime:
    instances = []
    def __init__(self, stopped, downloads=None):
        self.stopped = stopped
        self.browser = None
        self.calls = []
        self.closed = False
        self.instances.append(self)
    async def call(self, name, *args):
        self.calls.append((name, args))
        if self.stopped.is_set():
            raise InterruptedError()
        if name == "start":
            self.browser = True
            return OBS
        if name == "execute":
            return "Text entry verified.", OBS
        if name == "read":
            return args[0], "Source", "A sufficiently detailed source about robot control. " * 20
    async def aclose(self):
        self.closed = True


@pytest.fixture
def manager(monkeypatch):
    FakeRuntime.instances = []
    monkeypatch.setattr(service, "BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(service, "WindowsRuntime", FakeRuntime)
    monkeypatch.setattr(config, "BROWSER_AUTOMATION_ENABLED", True)
    return service.AutomationService()


async def until(predicate):
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(.001)
    raise AssertionError("Task did not reach expected state")


def test_approval_is_required_consumed_once_and_cleanup_runs(manager, monkeypatch):
    async def plan(job):
        if job.steps:
            return Step(action="done", reason="Verified visible result", value="Task result is visible.")
        return Step(action="fill", reason="Enter owner's exact search", target=1, value="robot control")
    monkeypatch.setattr(manager, "_plan", plan)
    async def scenario():
        assert (await manager.handle("browser task find robot control", "ollama")).success
        await until(lambda: manager.job.pending is not None)
        runtime = FakeRuntime.instances[0]
        assert not any(c[0] == "execute" for c in runtime.calls)
        assert manager.status().awaiting_reply
        assert (await manager.handle("browser yes", "ollama")).success
        assert not (await manager.handle("browser yes", "ollama")).success
        await manager.task
        assert sum(c[0] == "execute" for c in runtime.calls) == 1
        assert manager.job.state == "completed" and runtime.closed
    asyncio.run(scenario())


def test_stop_invalidates_late_plans_and_keeps_one_task(manager, monkeypatch):
    async def scenario():
        entered = asyncio.Event()
        async def plan(job):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(manager, "_plan", plan)
        await manager.handle("browser task a task", "ollama")
        await entered.wait()
        assert not (await manager.handle("research another task", "ollama")).success
        assert (await manager.handle("browser stop", "ollama")).success
        await manager.task
        assert manager.job.pending is None and manager.job.state == "cancelled"
        assert FakeRuntime.instances[0].closed
        assert not any(c[0] == "execute" for c in FakeRuntime.instances[0].calls)
    asyncio.run(scenario())


def test_repeated_stop_and_shutdown_do_not_interrupt_cleanup(manager, monkeypatch):
    async def scenario():
        cleanup_started, finish_cleanup = asyncio.Event(), asyncio.Event()
        async def plan(job):
            await asyncio.Event().wait()
        async def close(runtime):
            cleanup_started.set()
            await finish_cleanup.wait()
            runtime.closed = True
        monkeypatch.setattr(manager, "_plan", plan)
        monkeypatch.setattr(FakeRuntime, "aclose", close)
        await manager.handle("browser task a task", "ollama")
        await until(lambda: len(FakeRuntime.instances) == 1)
        await manager.handle("browser stop", "ollama")
        await cleanup_started.wait()
        await manager.handle("browser stop", "ollama")
        closing = asyncio.create_task(manager.close())
        await asyncio.sleep(0)
        finish_cleanup.set()
        await closing
        assert FakeRuntime.instances[0].closed
    asyncio.run(scenario())


def test_expired_approval_cannot_execute(manager, monkeypatch):
    monkeypatch.setattr(service, "APPROVAL_SECONDS", .01)
    async def plan(job):
        return Step(action="click", reason="Click Search", target=1)
    monkeypatch.setattr(manager, "_plan", plan)
    async def scenario():
        await manager.handle("browser task a task", "ollama")
        await manager.task
        assert manager.job.state == "failed" and "timed out" in manager.job.phase
        assert not (await manager.handle("browser yes", "ollama")).success
        assert not any(c[0] == "execute" for c in FakeRuntime.instances[0].calls)
    asyncio.run(scenario())


def test_stop_before_worker_starts_and_shutdown_are_clean(manager):
    async def scenario():
        await manager.handle("browser task a task", "ollama")
        await manager.close()  # cancellation can happen before _run's try/finally starts
        await asyncio.sleep(0)
        assert manager.job.state == "cancelled" and not FakeRuntime.instances
    asyncio.run(scenario())


def test_remote_and_disabled_automation_never_start_resources(manager, monkeypatch):
    async def scenario():
        for text in ("research robots", "browser yes", "browser stop", "research report", "browser status"):
            assert not (await manager.handle(text, "ollama", remote=True)).success
        monkeypatch.setattr(config, "BROWSER_AUTOMATION_ENABLED", False)
        assert not (await manager.handle("browser task robots", "ollama")).success
        assert not manager.active and not FakeRuntime.instances
    asyncio.run(scenario())


def test_research_bounds_deduplication_visible_default_and_partial_report(manager, monkeypatch, tmp_path):
    calls = []
    def search(query):
        calls.append(query)
        return [SimpleNamespace(url=f"https://example.com/{i}") for i in range(9)]
    monkeypatch.setattr(research, "_search", search)
    async def scenario():
        await manager.handle("research robot control", "ollama")
        await manager.task
        runtime = FakeRuntime.instances[0]
        assert runtime.calls[0] == ("start", (False,))
        assert sum(c[0] == "read" for c in runtime.calls) == 6
        assert manager.job.source_count == 6 and runtime.closed
        assert manager.job.report_path.is_file() and manager.job.report_path.parent == config.MEMORY_DIR / "research_reports"
        assert manager.job.state == "partial"  # no synthesis enabled in isolated tests
        report = (await manager.handle("research report", "ollama")).message
        assert "Source excerpts" in report and "not conclusions" in report
        assert not list(manager.job.report_path.parent.glob("*.tmp"))
    asyncio.run(scenario())


def test_synthesis_rejects_fabricated_quotes_and_preserves_source_ids(monkeypatch):
    monkeypatch.setattr(config, "AI_LANGUAGE_ENABLED", True)
    async def complete(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"findings": [{"claim": "False conclusion", "source": 1,
                                                                  "quote": "not in the page"}], "uncertainties": []}))
    monkeypatch.setattr(research, "complete_with_failover", complete)
    source = {"id": 1, "title": "Evidence", "url": "https://example.com", "text": "Original page evidence."}
    assert asyncio.run(research.synthesize("robots", [source], "ollama")) is None


def test_copied_quote_cannot_bypass_claim_support_review(monkeypatch):
    monkeypatch.setattr(config, "AI_LANGUAGE_ENABLED", True)
    replies = iter([
        {"findings": [{"claim": "Reinforcement learning uses PID feedback", "source": 1,
                       "quote": "PID uses feedback."}], "uncertainties": []},
        {"checks": [{"index": 0, "supported": False}]},
    ])
    async def complete(*args, **kwargs):
        return SimpleNamespace(content=json.dumps(next(replies)))
    monkeypatch.setattr(research, "complete_with_failover", complete)
    source = {"id": 1, "title": "PID", "url": "https://example.com", "text": "PID uses feedback."}
    assert asyncio.run(research.synthesize("compare controllers", [source], "ollama")) is None


def test_universal_scope_requires_support_in_the_actual_quote(monkeypatch):
    monkeypatch.setattr(config, "AI_LANGUAGE_ENABLED", True)
    async def complete(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"findings": [{"claim": "Both methods require tuning",
            "source": 1, "quote": "PID needs tuning."}], "uncertainties": []}))
    monkeypatch.setattr(research, "complete_with_failover", complete)
    source = {"id": 1, "title": "PID", "url": "https://example.com", "text": "PID needs tuning."}
    assert asyncio.run(research.synthesize("compare methods", [source], "ollama")) is None


def test_automation_proposal_policy_is_explicit_and_does_not_enable_tools(monkeypatch):
    from providers.policy import check_allowed
    from providers.failover import complete_with_failover
    from core.errors import ProviderError
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "AI_LANGUAGE_ENABLED", True)
    monkeypatch.setattr(config, "BROWSER_AUTOMATION_ENABLED", False)
    with pytest.raises(ProviderError):
        check_allowed("automation_proposal")
    monkeypatch.setattr(config, "BROWSER_AUTOMATION_ENABLED", True)
    check_allowed("automation_proposal")
    with pytest.raises(ProviderError):
        asyncio.run(complete_with_failover("ollama", [], "", 10, purpose="automation_proposal", tools=["unsafe"]))
