import asyncio
import copy
from types import SimpleNamespace

import pytest

from interfaces.api.routes import chat, voice
from services.automation import intent
from services.phone import bridge, commands, transport


class FakeTransport:
    owner = ":1.42"
    bus_id = "a" * 32

    def __init__(self):
        self.ids = ["phone1"]
        self.paired = self.reachable = True
        self.notification_ids = ["1", "2"]
        self.rows = {n: {"internalId": "app|" + n, "appName": "Messages", "title": "Friend " + n,
                         "text": "Private incoming " + n, "ticker": "", "replyId": "reply" + n}
                     for n in self.notification_ids}
        self.sent = []
        self.rings = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def devices(self):
        return self.ids

    def properties(self, device, notification=None):
        return copy.deepcopy(self.rows.get(notification, {})) if notification else {
            "name": "Android " + device, "isPaired": self.paired, "isReachable": self.reachable}

    def notifications(self, device):
        return self.notification_ids

    def reply(self, device, reply_id, message):
        self.sent.append((device, reply_id, message))

    def ring(self, device):
        self.rings.append(device)


@pytest.fixture
def phone(monkeypatch):
    connection = FakeTransport()
    service = bridge.PhoneBridge(lambda: connection)
    monkeypatch.setattr(bridge, "bridge", service)
    return service, connection


def say(message):
    return asyncio.run(intent.try_system_action(message, "openrouter"))


def select(phone):
    service, _ = phone
    service.list_notifications()
    service.read(1)


def test_list_select_draft_confirm_preserves_exact_text_and_consumes_once(phone):
    service, connection = phone
    assert "1. Messages: Friend 2" in say("read my phone notifications").message
    assert "Private incoming 2" in say("read phone notification 1").message
    result = say("reply that I'll call in ten minutes. Okay?")
    assert "Friend 2" in result.message and "I'll call in ten minutes. Okay?" in result.message
    assert result.memory_message == commands.PRIVATE_MEMORY and not connection.sent
    result = say("yes")
    assert result.success and "submitted" in result.message
    assert connection.sent == [("phone1", "reply2", "I'll call in ten minutes. Okay?")]
    assert not intent.is_awaiting_confirmation()
    assert not commands.private_turn("yes")


@pytest.mark.parametrize("change", ["text", "owner", "bus_id", "replyId", "missing", "device", "expired"])
def test_reply_refuses_changed_notification_connection_or_expiry(phone, monkeypatch, change):
    service, connection = phone
    select(phone)
    say("reply that I'll be there.")
    if change in ("text", "replyId"):
        connection.rows["2"][change] = "changed"
    elif change == "owner":
        connection.owner = ":1.43"
    elif change == "bus_id":
        connection.bus_id = "b" * 32
    elif change == "missing":
        connection.rows.pop("2")
    elif change == "device":
        connection.ids = ["different"]
    else:
        service.listed_at -= 200
    assert not say("yes").success
    assert not connection.sent and not intent.is_awaiting_confirmation()


def test_multiple_phones_require_selection_and_selection_survives_new_bridge(phone):
    service, connection = phone
    connection.ids.append("phone2")
    with pytest.raises(transport.PhoneError, match="Several"):
        service.list_notifications()
    assert "Using Android phone2" in say("use phone phone2").message
    restored = bridge.PhoneBridge(lambda: connection)
    restored.list_notifications()
    assert all(row["device"] == "phone2" for row in restored.items)
    assert say("forget my phone").success
    assert not service.items and service.selected is None


@pytest.mark.parametrize("field", ["paired", "reachable"])
def test_unpaired_or_disconnected_phone_cannot_be_read_or_rung(phone, field):
    service, connection = phone
    setattr(connection, field, False)
    assert not say("read my phone notifications").success
    assert not say("ring my phone").success
    assert not connection.rings


def test_cancel_expire_or_new_turn_never_submits_a_draft(phone, monkeypatch):
    _, connection = phone
    select(phone)
    say("reply that Hi!")
    assert say("no").success and not connection.sent
    select(phone)
    say("reply that Hello!")
    pending = intent._pending[False]
    intent._pending[False] = pending._replace(expires_at=0)
    assert not say("yes").success and not connection.sent
    select(phone)
    say("reply that Morning!")
    say("what time is it")
    assert not intent.is_awaiting_confirmation() and not connection.sent


def test_non_reply_notification_and_empty_context_are_explicit_failures(phone):
    _, connection = phone
    assert not say("reply that Hello").success
    select(phone)
    connection.rows["2"]["replyId"] = ""
    select(phone)
    assert not say("reply that Hello").success
    assert not connection.sent


def test_phone_turns_never_reach_cloud_search_memory_or_remote_confirmation(phone, monkeypatch):
    _, connection = phone
    def forbidden(*args, **kwargs):
        pytest.fail("Private phone data escaped its local command path")
    monkeypatch.setattr(chat._memory, "get_recent_history", forbidden)
    monkeypatch.setattr(chat._memory, "save_message", forbidden)
    monkeypatch.setattr(chat, "build_search_context", forbidden)
    result = asyncio.run(chat.chat(chat.ChatRequest(message="read my phone notifications")))
    assert "Friend" in result.response and result.private
    result = asyncio.run(voice._reply("read phone notification 1", voice.VoiceRequest(speak=False)))
    assert "Private incoming" in result.response and result.private
    say("reply that Confirmed private reply.")
    token = intent.remote_request.set(True)
    try:
        assert not say("read my phone notifications").success
        assert not say("reply that Attack").success
        assert not commands.private_turn("yes")
        assert False in intent._pending
    finally:
        intent.remote_request.reset(token)
    assert say("yes").success and len(connection.sent) == 1


def test_malicious_ids_and_missing_installation_fail_before_native_calls(monkeypatch):
    assert commands.match_command("find my phone") is None  # preserve existing file search
    for value in ("../phone", "a/b", "", "phone; --ring", "a\x00b"):
        with pytest.raises(transport.PhoneError):
            transport.identifier(value)
    monkeypatch.delenv("KDECONNECT_DIR", raising=False)
    monkeypatch.setattr(transport.shutil, "which", lambda _: None)
    monkeypatch.setattr(transport.Path, "is_file", lambda _: False)
    with pytest.raises(transport.PhoneError, match="Install KDE Connect"):
        transport.installation()


def test_duplicate_concurrent_confirmation_is_a_private_single_submission(phone):
    _, connection = phone
    select(phone)
    say("reply that Just once.")
    async def confirm():
        return await asyncio.gather(commands.handle("yes", "openrouter"), commands.handle("yes", "openrouter"))
    results = asyncio.run(confirm())
    assert len(connection.sent) == 1
    assert sum(result.success for result in results) == 1
    assert all(result.memory_message == commands.PRIVATE_MEMORY for result in results)


def test_desktop_private_notification_does_not_record_or_mirror_contents(monkeypatch):
    from services.mind.cognition import cognition
    from services.reminders import service
    from services.telegram import client as telegram
    from interfaces.tray.tray import FridayTray
    operations, mirrored, toasts = [], [], []
    from contextlib import contextmanager
    @contextmanager
    def operation(kind, channel, text, **kwargs):
        operations.append(text)
        yield SimpleNamespace(finish=lambda _: None)
    monkeypatch.setattr(cognition, "operation", operation)
    monkeypatch.setattr(telegram, "mirror", lambda *args: mirrored.append(args))
    monkeypatch.setattr(service.subprocess, "run", lambda *args, **kwargs:
                        toasts.append(kwargs["env"]["FRIDAY_TOAST_BODY"]) or SimpleNamespace(returncode=0, stderr=""))
    tray = object.__new__(FridayTray)
    tray.notify("Secret phone notification and exact draft", private=True)
    assert toasts == ["Secret phone notification and exact draft"]
    assert operations == ["Private local assistant response"] and not mirrored


def test_popup_omits_phone_drafts_from_suggestion_learning_and_preserves_private_reply(monkeypatch):
    from interfaces.popup import app
    from interfaces.tray import backend
    state = dict(app._state, offered=["open spotify"], private=False, awaiting_reply=False, target_window=None,
                 request_generation=0, computer=False, keyboard=())
    monkeypatch.setattr(app, "_state", state)
    outcomes, callbacks = [], []
    monkeypatch.setattr(app.backend, "bar_outcome", lambda *args: outcomes.append(args))
    class Immediate:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    monkeypatch.setattr(app.threading, "Thread", Immediate)
    app._report_guesses("reply that Private draft.")
    assert outcomes == [(["open spotify"], None)]
    monkeypatch.setattr(app.backend, "chat", lambda _: backend.ChatReply("Private response", False, private=True))
    monkeypatch.setattr(app.computer_bar, "before_request", lambda *a: None)
    monkeypatch.setattr(app, "_chat_done_listener", None)
    app._send_chat_message("read my phone notifications")
    assert state["private"]
    monkeypatch.setattr(app, "_reply_listener", lambda *args: callbacks.append(args))
    monkeypatch.setattr(app, "_show_ask", lambda *args: None)
    monkeypatch.setattr(app, "user32", SimpleNamespace(SetWindowTextW=lambda *a: None,
                                                      SendMessageW=lambda *a: None, SetTimer=lambda *a: None))
    app._show_reply(1, 2)
    assert callbacks == [("Private response", False, True)]
