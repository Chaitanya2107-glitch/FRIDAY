from types import SimpleNamespace

import pytest

from interfaces.popup import app as popup
from interfaces.tray.backend import ChatReply


@pytest.fixture
def bar(monkeypatch):
    events = []
    text = "\\c open the menu"

    def read_text(hwnd, buffer, length):
        buffer.value = text

    fake = SimpleNamespace(
        GetWindowTextLengthW=lambda hwnd: len(text), GetWindowTextW=read_text,
        SendMessageW=lambda *a: None, SetWindowTextW=lambda *a: None,
        ShowWindow=lambda hwnd, mode: events.append(("show", mode)),
        KillTimer=lambda *a: None, SetTimer=lambda *a: None,
        IsWindow=lambda hwnd: True, GetForegroundWindow=lambda: 17,
        SetForegroundWindow=lambda hwnd: events.append(("focus", hwnd)),
        SetFocus=lambda hwnd: pytest.fail("computer proposal took keyboard focus"),
    )
    state = dict(popup._state, visible=True, ask=False, handy=False, offered=[], target_window=17)
    monkeypatch.setattr(popup, "user32", fake)
    monkeypatch.setattr(popup.computer_bar, "user32", fake)
    monkeypatch.setattr(popup, "_state", state)
    monkeypatch.setattr(popup, "_hint_hwnd", None)
    monkeypatch.setattr(popup, "_submit_listener", None)
    monkeypatch.setattr(popup, "_chat_done_listener", None)
    monkeypatch.setattr(popup, "_reply_listener", None)
    monkeypatch.setattr(popup.time, "sleep", lambda *a: None)
    return SimpleNamespace(events=events, fake=fake, state=state)


def test_submission_restores_focus_before_request_starts(bar, monkeypatch):
    class Thread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            bar.events.append(("request", None))

    monkeypatch.setattr(popup, "threading", SimpleNamespace(Thread=Thread))
    popup._submit(1, 2)
    assert bar.events == [("show", popup.SW_HIDE), ("focus", 17), ("request", None)]
    assert not bar.state["visible"]


def test_proposal_shows_without_stealing_focus(bar):
    bar.state.update(computer=True, visible=False, response="Review the click", awaiting_reply=True)
    popup._show_reply(1, 2)
    assert bar.events == [("show", popup.SW_SHOWNOACTIVATE)]
    assert bar.state["ask"] and bar.state["visible"]


def test_failed_focus_restore_prevents_backend_request(bar, monkeypatch):
    bar.fake.GetForegroundWindow = lambda: 18
    monkeypatch.setattr(popup.backend, "chat", lambda *a: pytest.fail("request ran with the wrong foreground window"))
    popup._send_chat_message("\\c yes")
    assert "return focus" in bar.state["response"]
    assert bar.state["response_ready"]


def test_stop_does_not_depend_on_restoring_focus(bar, monkeypatch):
    bar.fake.GetForegroundWindow = lambda: 18
    calls = []

    def chat(message):
        calls.append(message)
        return ChatReply("Stopped", False)

    monkeypatch.setattr(popup.backend, "chat", chat)
    popup._send_chat_message("\\c stop")
    assert calls == ["\\c stop"]


def test_computer_error_stays_visible_long_enough_to_read(bar):
    timers = []
    bar.fake.SetTimer = lambda hwnd, timer, duration, callback: timers.append((timer, duration))
    bar.state.update(computer=True, visible=False, response="No desktop input ran. Vision AI unavailable.",
                     awaiting_reply=False)
    popup._show_reply(1, 2)
    assert bar.state["ask"] and bar.state["visible"]
    assert timers == [(popup.ASK_TIMER_ID, popup.ASK_SHOW_MS)]


def test_screen_query_restores_the_app_before_request(bar, monkeypatch):
    text = "what am I doing?"
    bar.fake.GetWindowTextLengthW = lambda hwnd: len(text)
    bar.fake.GetWindowTextW = lambda hwnd, buffer, length: setattr(buffer, "value", text)
    thread = SimpleNamespace(start=lambda: bar.events.append(("request", None)))
    monkeypatch.setattr(popup, "threading", SimpleNamespace(Thread=lambda **kwargs: thread))
    popup._submit(1, 2)
    assert bar.events == [("show", popup.SW_HIDE), ("focus", 17), ("request", None)]
    assert bar.state["screen_query"] and not bar.state["computer"]


def test_screen_query_cannot_read_a_different_app_after_failed_focus_restore(bar, monkeypatch):
    bar.fake.GetForegroundWindow = lambda: 18
    monkeypatch.setattr(popup.backend, "chat", lambda *a: pytest.fail("screen query read the wrong app"))
    popup._send_chat_message("what am I reading")
    assert "return focus" in bar.state["response"] and bar.state["response_ready"]


def test_screen_answer_stays_private_and_does_not_take_focus(bar, monkeypatch):
    replies = []
    monkeypatch.setattr(popup, "_reply_listener", lambda *args: replies.append(args))
    bar.state.update(computer=False, screen_query=True, visible=False, private=True,
                     command=True, response="A local interpretation.", awaiting_reply=False)
    popup._show_reply(1, 2)
    assert bar.events == [("show", popup.SW_SHOWNOACTIVATE)]
    assert replies == [("A local interpretation.", True, True)]


def test_ordinary_private_conversation_replaces_sending_and_stays_readable(bar):
    edits, timers = [], []
    bar.fake.SetWindowTextW = lambda hwnd, text: edits.append(text)
    bar.fake.SetTimer = lambda hwnd, timer, duration, callback: timers.append((timer, duration))
    bar.state.update(computer=False, screen_query=False, visible=True, ask=False, private=True,
                     command=False, response="An activity-aware personal reply.", awaiting_reply=False)
    popup._show_reply(1, 2)
    assert "An activity-aware personal reply." in edits
    assert bar.state["ask"] and timers == [(popup.ASK_TIMER_ID, popup.ASK_SHOW_MS)]
