import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from interfaces.api.routes import chat, clipboard as clipboard_route
from services.automation import actions, clipboard, intent
from services.automation.clipboard_history import ClipboardHistory
from services.automation.device_commands import match_device_command
from services.automation.intent import ActionResult, try_system_action
from services.automation.system_control import AutomationError

LOCAL = "http://127.0.0.1:8000"


@pytest.fixture
def fake_clipboard(monkeypatch):
    state = SimpleNamespace(sequence=1, text="hello", private=False, written=[])
    monkeypatch.setattr(clipboard, "sequence_number", lambda: state.sequence)
    monkeypatch.setattr(clipboard, "get_text", lambda: state.text)
    monkeypatch.setattr(clipboard, "is_private", lambda: state.private)

    def set_text(text):
        state.written.append(text)
        state.text = text
        state.sequence += 1
    monkeypatch.setattr(clipboard, "set_text", set_text)
    return state


# ── Recording ─────────────────────────────────────────────────────────────────

def test_newest_first_without_duplicates():
    history = ClipboardHistory()
    for text in ["one", "two", "one", "   "]:
        history.record(text)
    assert history.items() == ["one", "two"]


def test_keeps_only_the_most_recent_items():
    history = ClipboardHistory(max_items=3)
    for i in range(5):
        history.record(f"item {i}")
    assert history.items() == ["item 4", "item 3", "item 2"]


def test_records_only_when_something_new_is_copied(fake_clipboard):
    history = ClipboardHistory()
    history.check_clipboard()
    history.check_clipboard()  # same sequence number — nothing new was copied

    fake_clipboard.sequence, fake_clipboard.text = 2, "world"
    history.check_clipboard()

    assert history.items() == ["world", "hello"]


def test_skips_what_password_managers_mark_private(fake_clipboard):
    fake_clipboard.private = True
    history = ClipboardHistory()
    history.check_clipboard()
    assert history.items() == []


def test_non_text_clipboard_is_ignored(fake_clipboard):
    fake_clipboard.text = None
    history = ClipboardHistory()
    history.check_clipboard()
    assert history.items() == []


def test_busy_clipboard_is_retried_next_tick(fake_clipboard, monkeypatch):
    history = ClipboardHistory()

    def busy():
        raise clipboard.ClipboardError("the clipboard is busy")
    monkeypatch.setattr(clipboard, "get_text", busy)
    with pytest.raises(clipboard.ClipboardError):
        history.check_clipboard()

    monkeypatch.setattr(clipboard, "get_text", lambda: "hello")
    history.check_clipboard()
    assert history.items() == ["hello"]


# ── List / restore / clear ────────────────────────────────────────────────────

def test_list_restore_and_clear(fake_clipboard):
    history = ClipboardHistory()
    for text in ["first", "second\nwith   spaces", "third"]:
        history.record(text)

    assert history.list_message() == (
        "Clipboard history (newest first):\n1. third\n2. second with spaces\n3. first"
        '\nSay "copy clipboard item 2" to put one back.'
    )
    assert history.restore(3) == "Copied item 3 back to the clipboard: first"
    assert fake_clipboard.written == ["first"]
    assert history.items()[0] == "first"
    assert history.clear() == "Clipboard history cleared."
    assert history.list_message() == "Your clipboard history is empty."


@pytest.mark.parametrize("number", [0, 4])
def test_restore_unknown_item(fake_clipboard, number):
    history = ClipboardHistory()
    for text in ["a", "b", "c"]:
        history.record(text)
    with pytest.raises(AutomationError, match="no clipboard item"):
        history.restore(number)


# ── Commands ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("clipboard history", {"action": "list_clipboard_history"}),
    ("show my clipboard history", {"action": "list_clipboard_history"}),
    ("list clipboard history", {"action": "list_clipboard_history"}),
    ("copy clipboard item 3", {"action": "restore_clipboard_item", "number": 3}),
    ("restore clipboard item 2", {"action": "restore_clipboard_item", "number": 2}),
    ("copy item 4 from my clipboard history", {"action": "restore_clipboard_item", "number": 4}),
    ("clear clipboard history", {"action": "clear_clipboard_history"}),
    ("read my clipboard", {"action": "read_clipboard"}),
    ("copy hello world to clipboard", {"action": "write_clipboard", "text": "hello world"}),
])
def test_clipboard_commands(message, expected):
    assert match_device_command(message) == {"type": "system", **expected}


@pytest.fixture
def intent_history(monkeypatch, fake_clipboard):
    history = ClipboardHistory()
    for text in ["api-key-123", "hello"]:
        history.record(text)
    monkeypatch.setattr(actions, "clipboard_history", history)  # actions.py runs the command
    monkeypatch.setattr(intent, "get_provider", lambda name: pytest.fail("no AI call expected"))
    return history


def ask(message):
    return asyncio.run(try_system_action(message, "openrouter"))


def test_chat_commands_reach_the_history(intent_history, fake_clipboard):
    assert ask("clipboard history").message.startswith("Clipboard history (newest first):\n1. hello\n2. api-key-123")
    assert ask("copy clipboard item 2").message == "Copied item 2 back to the clipboard: api-key-123"
    assert fake_clipboard.written == ["api-key-123"]
    assert ask("clear clipboard history") == ActionResult(True, "Clipboard history cleared.")
    assert ask("copy clipboard item 1") == ActionResult(False, "Your clipboard history is empty.")


def test_history_contents_are_not_saved_to_chat_memory(intent_history, monkeypatch):
    saved = []
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(
        get_recent_history=lambda: [],
        save_message=lambda role, content: saved.append((role, content)),
    ))
    monkeypatch.setattr("providers.failover.get_provider",lambda name: None)
    client = TestClient(create_app(), base_url=LOCAL)

    assert "api-key-123" in client.post("/api/v1/chat", json={"message": "clipboard history"}).json()["response"]
    assert "api-key-123" in client.post("/api/v1/chat", json={"message": "copy clipboard item 2"}).json()["response"]
    assert all("api-key-123" not in content for _, content in saved)


def test_tray_endpoints(monkeypatch):
    history = ClipboardHistory()
    history.record("hello")
    monkeypatch.setattr(clipboard_route, "clipboard_history", history)
    client = TestClient(create_app(), base_url=LOCAL)

    assert client.get("/api/v1/clipboard/history").json() == {"items": ["hello"]}
    assert client.delete("/api/v1/clipboard/history").json() == {"message": "Clipboard history cleared."}
    assert history.items() == []
