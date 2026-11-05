import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from interfaces.api.routes import chat
from services.automation import intent
from services.automation.intent import ActionResult, try_system_action
from services.search import web_search


@pytest.fixture(autouse=True)
def no_pending_confirmation():
    for remote in (False, True):
        with channel(remote):
            intent.cancel_pending_confirmation()
    yield
    for remote in (False, True):
        with channel(remote):
            intent.cancel_pending_confirmation()


@contextmanager
def channel(remote):
    token = intent.remote_request.set(remote)
    try:
        yield
    finally:
        intent.remote_request.reset(token)


@pytest.fixture
def downloads(tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    for name in ("photo.jpg", "report.pdf", "song.mp3"):
        (folder / name).write_text("x")
    (folder / ".hidden").write_text("x")
    (folder / "Existing").mkdir()
    return folder


def ask(message):
    return asyncio.run(try_system_action(message, "openrouter"))


def request_organise(folder):
    return intent._execute({"type": "system", "action": "organise_folder", "path": str(folder)})


def assert_untouched(folder):
    assert sorted(p.name for p in folder.iterdir()) == [".hidden", "Existing", "photo.jpg", "report.pdf", "song.mp3"]


def test_organise_asks_first_and_moves_nothing(downloads):
    result = request_organise(downloads)
    assert result.message.startswith("Organise Downloads? This moves 3 files into subfolders.")
    assert_untouched(downloads)


@pytest.mark.parametrize("reply", ["yes", "Yes, do it.", "go ahead", "OK"])
def test_yes_runs_the_organise(downloads, reply):
    request_organise(downloads)

    assert ask(reply) == ActionResult(True, "Organised 3 files in Downloads.")
    assert (downloads / "Images" / "photo.jpg").exists()
    assert (downloads / "Documents" / "report.pdf").exists()
    assert (downloads / "Audio" / "song.mp3").exists()


@pytest.mark.parametrize("reply", ["no", "Cancel.", "never mind", "don’t"])
def test_no_cancels_and_a_later_yes_does_nothing(downloads, reply):
    request_organise(downloads)

    assert ask(reply) == ActionResult(True, "Okay, cancelled. Nothing was changed.")
    assert ask("yes") is None
    assert_untouched(downloads)


def test_unrelated_message_drops_the_pending_action(downloads, monkeypatch):
    monkeypatch.setattr(intent, "get_provider", lambda name: pytest.fail("no AI call expected"))
    request_organise(downloads)

    assert ask("what's the weather like") is None
    assert ask("yes") is None
    assert_untouched(downloads)


def test_expired_confirmation_does_nothing(downloads, monkeypatch):
    monkeypatch.setattr(intent, "CONFIRM_TIMEOUT_SECONDS", -1)
    request_organise(downloads)

    result = ask("yes")

    assert result.success is False and "timed out" in result.message
    assert_untouched(downloads)


def test_empty_folder_needs_no_confirmation(tmp_path):
    assert request_organise(tmp_path) == ActionResult(True, f"There's nothing to organise in {tmp_path.name}.")
    assert ask("yes") is None


def test_missing_folder_reports_error(tmp_path):
    assert request_organise(tmp_path / "nope") == ActionResult(False, "Couldn't find the folder nope.")


def test_typed_command_goes_through_confirmation(downloads, monkeypatch):
    monkeypatch.setitem(intent.FOLDER_MAP, "downloads", str(downloads))

    assert ask("clean my downloads").message.startswith("Organise Downloads?")
    assert_untouched(downloads)
    assert ask("yes").message == "Organised 3 files in Downloads."


def _fake_memory():
    return SimpleNamespace(get_recent_history=lambda: [], save_message=lambda role, content: None)


def test_chat_round_trip_confirms_then_organises(downloads, monkeypatch):
    monkeypatch.setitem(intent.FOLDER_MAP, "downloads", str(downloads))
    monkeypatch.setattr(chat, "_memory", _fake_memory())
    monkeypatch.setattr("providers.failover.get_provider",lambda name: None)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")

    first = client.post("/api/v1/chat", json={"message": "organise downloads"}).json()
    assert first["response"].startswith("Organise Downloads?")
    assert first["awaiting_reply"] is True  # tells the command bar to stay open for the answer
    assert_untouched(downloads)

    second = client.post("/api/v1/chat", json={"message": "yes"}).json()
    assert second["response"] == "Organised 3 files in Downloads."
    assert second["awaiting_reply"] is False
    assert (downloads / "Images" / "photo.jpg").exists()


def test_web_search_message_cancels_pending_action(downloads, monkeypatch):
    async def complete(messages, system_prompt, max_tokens):
        return SimpleNamespace(content="answer", provider="fake", model="fake", tokens_used=1)
    monkeypatch.setattr(chat, "_memory", _fake_memory())
    monkeypatch.setattr("providers.failover.get_provider",lambda name: SimpleNamespace(complete=complete))
    monkeypatch.setattr(web_search, "_search", lambda query: [])

    request_organise(downloads)
    resp = TestClient(create_app(), base_url="http://127.0.0.1:8000").post("/api/v1/chat", json={"message": "look up folder organising tips"})

    assert resp.status_code == 200
    assert ask("yes") is None
    assert_untouched(downloads)


def test_system_endpoint_refuses_to_organise(monkeypatch, downloads):
    monkeypatch.setattr(intent.system, "organise_folder", lambda path: pytest.fail("must not organise"))

    resp = TestClient(create_app(), base_url="http://127.0.0.1:8000").post("/api/v1/system", json={"command": "organise downloads", "speak": False})

    assert resp.status_code == 500
    assert "confirmation" in resp.json()["message"]
    assert not intent.is_awaiting_confirmation()


@pytest.mark.parametrize("origin", [False, True], ids=["laptop", "telegram"])
@pytest.mark.parametrize("reply", ["yes", "no", "what time is it"])
def test_other_channel_cannot_consume_confirmation(origin, reply, monkeypatch):
    executed = []
    monkeypatch.setattr(intent, "_execute", lambda parsed, confirmed=False: executed.append(parsed))
    with channel(origin):
        intent._ask_first({"action": "shutdown_pc"}, "Shut down?")

    with channel(not origin):
        assert not intent.is_awaiting_confirmation()
        assert asyncio.run(intent._handle_pending_reply(reply, "openrouter")) is None
        intent.cancel_pending_confirmation()

    with channel(origin):
        assert intent.is_awaiting_confirmation()
        asyncio.run(intent._handle_pending_reply("yes", "openrouter"))
        assert not intent.is_awaiting_confirmation()
    assert executed == [{"action": "shutdown_pc"}]


@pytest.mark.parametrize("first", [False, True], ids=["laptop-first", "telegram-first"])
def test_simultaneous_confirmations_execute_once_in_their_channel(first, monkeypatch):
    executed = []

    def execute(parsed, confirmed=False):
        assert confirmed
        executed.append((intent.remote_request.get(), parsed["action"]))
        return ActionResult(True, parsed["action"])

    monkeypatch.setattr(intent, "_execute", execute)
    for remote, action in ((False, "shutdown_pc"), (True, "restart_pc")):
        with channel(remote):
            intent._ask_first({"action": action}, "Confirm?")

    for remote in (first, not first):
        with channel(remote):
            result = asyncio.run(intent._handle_pending_reply("yes", "openrouter"))
            assert result.message == ("restart_pc" if remote else "shutdown_pc")
            assert asyncio.run(intent._handle_pending_reply("yes", "openrouter")) is None
    assert executed == [(remote, "restart_pc" if remote else "shutdown_pc") for remote in (first, not first)]


def test_expiration_and_cancellation_only_clear_their_channel(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(intent.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(intent, "_execute", lambda *a, **kw: pytest.fail("must not execute"))
    with channel(False):
        intent._ask_first({"action": "shutdown_pc"}, "Shut down?")
    now[0] = 150.0
    with channel(True):
        intent._ask_first({"action": "restart_pc"}, "Restart?")
    now[0] = 221.0
    with channel(False):
        result = asyncio.run(intent._handle_pending_reply("yes", "openrouter"))
        assert not result.success and "timed out" in result.message
        assert not intent.is_awaiting_confirmation()
    with channel(True):
        assert intent.is_awaiting_confirmation()
        result = asyncio.run(intent._handle_pending_reply("no", "openrouter"))
        assert result.message == "Okay, cancelled. Nothing was changed."
        assert not intent.is_awaiting_confirmation()


def test_real_telegram_and_chat_paths_keep_their_power_confirmations(monkeypatch):
    from services.telegram import bot

    sent, executed = [], []
    monkeypatch.setattr(chat, "_memory", _fake_memory())
    monkeypatch.setattr(bot, "_pending", None)
    monkeypatch.setattr(intent.power, "run", lambda parsed: executed.append(parsed["action"]) or "Done.")

    async def say(chat_id, text, links=None):
        sent.append(text)

    monkeypatch.setattr(bot, "say", say)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    first = client.post("/api/v1/chat", json={"message": "shut down the laptop"}).json()
    assert first["awaiting_reply"] is True

    asyncio.run(bot._run(42, "what time is it"))
    assert intent.is_awaiting_confirmation()
    asyncio.run(bot._run(42, "restart the laptop"))
    assert "Restart the laptop?" in sent[-1]

    local = client.post("/api/v1/chat", json={"message": "yes"}).json()
    assert local["response"] == "Done." and local["awaiting_reply"] is False
    assert executed == ["shutdown_pc"]
    asyncio.run(bot._run(42, "yes"))
    assert executed == ["shutdown_pc", "restart_pc"]
    assert intent.remote_request.get() is False
