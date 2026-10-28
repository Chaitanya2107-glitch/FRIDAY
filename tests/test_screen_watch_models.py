import asyncio
from datetime import datetime, timedelta
import json

import httpx
import pytest

from core.config import config
from services.mind.cognition import Cognition
from services.screen_watch import inference
from services.screen_watch.store import ScreenStore

NOW = datetime(2026, 10, 28, 15)


@pytest.fixture
def store(tmp_path):
    return ScreenStore(Cognition(tmp_path / "screen.db"))


def save(store, **updates):
    cfg = store.settings()
    values = dict(epoch=cfg["epoch"], session="run1", scope={"window": 1}, app="notepad",
                  summary="Graph lecture notes are visible.", activity="May be reading graphs.",
                  source="accessible_text", at=NOW)
    values.update(updates)
    return store.save(**values)


def test_store_defaults_off_and_never_confirms_a_personal_fact(store):
    assert not store.settings()["enabled"]
    assert not save(store)
    store.control("start")
    assert save(store)
    row = store.latest({"window": 1}, "run1", store.settings()["epoch"], NOW)
    assert row["source"] == "accessible_text"
    with store.db() as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='owner_activities'").fetchone()


@pytest.mark.parametrize("action", ["pause", "stop", "resume"])
def test_controls_fence_older_inference(store, action):
    store.control("start")
    epoch = store.settings()["epoch"]
    store.control(action)
    assert not save(store, epoch=epoch)


def test_summary_is_bound_to_session_window_and_capture_time(store):
    store.control("start")
    save(store)
    epoch = store.settings()["epoch"]
    assert store.latest({"window": 2}, "run1", epoch, NOW) is None
    assert store.latest({"window": 1}, "other", epoch, NOW) is None
    assert store.latest({"window": 1}, "run1", epoch, NOW - timedelta(seconds=1)) is None
    assert store.latest({"window": 1}, "run1", epoch, NOW + timedelta(seconds=76)) is None


def test_retention_bound_and_targeted_forget(store):
    store.control("start")
    for i in range(205):
        save(store, at=NOW + timedelta(seconds=i))
    with store.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM screen_observations").fetchone()[0] == 200
    epoch = store.settings()["epoch"]
    assert store.forget("graphs") == 200
    assert store.settings()["paused"] and store.settings()["epoch"] > epoch
    assert not save(store, epoch=epoch)
    store.control("resume")
    save(store)
    store.prune(NOW + timedelta(days=8))
    assert store.history(now=NOW + timedelta(days=8)) == []


def test_existing_forget_epoch_clears_new_derived_table(store):
    from services.mind.executive import clear_derived
    store.control("start")
    save(store)
    epoch = store.settings()["epoch"]
    with store.db() as conn:
        clear_derived(conn)
    assert store.history(now=NOW) == []
    assert not save(store, epoch=epoch)


@pytest.mark.parametrize("url", ["https://localhost:11434", "http://example.com", "http://127.0.0.1/private",
                               "http://user:pass@localhost:11434", "http://localhost:11434/?secret=1"])
def test_nonlocal_or_credentialed_endpoints_rejected(url):
    with pytest.raises(ValueError):
        inference.local_url(url)


def local_http(monkeypatch, *, remote_tags=False, remote_show=False, capabilities=None, done=True, tool=False, content=None):
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "local-text:latest")
    calls, clients = [], []
    def reply(request):
        body = json.loads(request.content) if request.content else {}
        calls.append((request.url.path, body))
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": name, **({"remote_host": "https://ollama.com"} if remote_tags else {})}
                for name in ("local-text:latest", inference.VISION_MODEL)]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={
                "capabilities": ["completion", "vision"] if capabilities is None else capabilities,
                **({"remote_model": "qwen-cloud"} if remote_show else {})})
        assert request.url.path == "/api/chat"
        value = content if content is not None else json.dumps({
            "summary": "A graph lecture is visible.", "activity": "Possibly reading graph notes.",
            "needs_vision": False, "sensitive": False})
        return httpx.Response(200, json={"done": done, "done_reason": "stop" if done else "length",
                                       "message": {"content": value, "tool_calls": [{"function": "run"}] if tool else []}})
    original = httpx.AsyncClient
    def client(**kwargs):
        clients.append(kwargs)
        return original(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    return calls, clients


def test_local_analysis_has_no_history_global_prompt_or_tools(monkeypatch):
    calls, clients = local_http(monkeypatch)
    result = asyncio.run(inference.analyze("notes", "SAFE_SYNTHETIC_VISIBLE_TEXT"))
    assert not result.sensitive
    assert [path for path, body in calls] == ["/api/tags", "/api/show", "/api/chat"]
    payload = calls[-1][1]
    assert payload["messages"][1]["content"].find("SAFE_SYNTHETIC_VISIBLE_TEXT") >= 0
    assert "tools" not in payload and payload["options"]["num_ctx"] == 4096
    assert len(payload["messages"]) == 2 and "primary role" not in payload["messages"][0]["content"]
    assert clients[0]["trust_env"] is False and clients[0]["follow_redirects"] is False


@pytest.mark.parametrize("remote", ["tags", "show"])
def test_localhost_cloud_proxy_is_rejected_before_any_screen_content(monkeypatch, remote):
    calls, _ = local_http(monkeypatch, remote_tags=remote == "tags", remote_show=remote == "show")
    with pytest.raises(ValueError):
        asyncio.run(inference.analyze("notes", "SYNTHETIC", b"image-bytes"))
    assert all(path != "/api/chat" for path, body in calls)
    assert "SYNTHETIC" not in str(calls)


@pytest.mark.parametrize("capabilities", ["not vision", ["completion"], None, True, {}])
def test_exact_vision_capability_required(monkeypatch, capabilities):
    # Explicit null needs its own response; the helper's default is a valid list.
    calls, _ = local_http(monkeypatch, capabilities=[] if capabilities is None else capabilities)
    with pytest.raises(ValueError):
        asyncio.run(inference.analyze("notes", "SYNTHETIC", b"image-bytes"))
    assert all(path != "/api/chat" for path, body in calls)


@pytest.mark.parametrize("updates", [{"done": False}, {"tool": True}, {"content": "not json"},
                                    {"content": '{"summary":"x","activity":"y","needs_vision":false,"sensitive":false,"command":"delete"}'}])
def test_incomplete_or_action_bearing_interpretations_are_not_accepted(monkeypatch, updates):
    local_http(monkeypatch, **updates)
    with pytest.raises(ValueError):
        asyncio.run(inference.analyze("notes", "SYNTHETIC"))


def test_secret_text_is_not_sent_to_any_endpoint(monkeypatch):
    calls, _ = local_http(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(inference.analyze("notes", "API_KEY: sk-testingabcdefghijklmnop"))
    assert not calls
