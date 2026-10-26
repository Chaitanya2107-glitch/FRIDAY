import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from core.errors import FridayError
from interfaces import protocol_handler
from interfaces.api.app import create_app
from services.activity.log import ActivityLog
from services.proactive import buttons, watcher
from services.reminders import service as reminder_service


def answer_of(link):
    query = parse_qs(urlsplit(link).query)
    return query["token"][0], query["answer"][0]


@pytest.fixture
def log(tmp_path, monkeypatch):
    log = ActivityLog(str(tmp_path / "a.db"))
    import services.activity.log as log_module
    monkeypatch.setattr(log_module, "activity_log", log)
    monkeypatch.setattr(watcher, "activity_log", log)
    return log


HABIT = {"habit": "time:app:code:weekday", "id": "s1"}


def test_habit_suggestion_has_buttons_and_open_it_opens(log, monkeypatch):
    shown = []
    monkeypatch.setattr(watcher, "show_toast", lambda title, text, links=None, **kw: shown.append((text, links)))
    monkeypatch.setattr(watcher.habits, "next_suggestion", lambda log, now: watcher.habits.Suggestion(
        "s1", "time:app:code:weekday", "You usually open code around 9:00 AM on weekdays. Open it?", "habit"))
    asyncio.run(watcher._suggest_habit(watcher.datetime.now()))

    text, links = shown[0]
    assert [label for label, _ in links] == ["Open it", "Not now", "Stop suggesting"]
    assert all(link.startswith("friday://habit?token=") for _, link in links)

    opened = []
    monkeypatch.setattr("services.automation.system_control.system.open_app", lambda app: opened.append(app) or "Opening Code.")
    assert buttons.respond(*answer_of(links[0][1])) == "Opening Code."
    assert opened == ["vs code"]

    with pytest.raises(FridayError, match="expired"):  # each notification answers once
        buttons.respond(*answer_of(links[1][1]))


def test_a_link_can_only_answer_what_friday_asked(log):
    links = buttons.offer("habit", **HABIT)
    token, _ = answer_of(links[0][1])
    with pytest.raises(FridayError, match="isn't on this notification"):
        buttons.respond(token, "snooze")
    with pytest.raises(FridayError, match="expired"):
        buttons.respond("made-up-token-from-a-web-page", "open")


def test_reminder_snooze(tmp_path, monkeypatch):
    store = reminder_service.ReminderService(str(tmp_path / "r.db"))
    monkeypatch.setattr(reminder_service, "reminders", store)
    links = buttons.offer("reminder", text="stretch")
    assert [label for label, _ in links] == ["Snooze 10 min"]
    assert buttons.respond(*answer_of(links[0][1])) == "Okay, I'll remind you again in 10 minutes: stretch."
    assert [r.text for r in store.pending()] == ["stretch"]


def test_toast_buttons_are_escaped_xml(monkeypatch):
    seen = {}

    def run(args, env, **kw):
        seen.update(env)
        return type("Done", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr(reminder_service.subprocess, "run", run)
    reminder_service.show_toast("t", "b", [("Open & go", "friday://habit?token=abc&answer=open")])
    assert seen["FRIDAY_TOAST_ACTIONS"] == (
        "<action content=\"Open &amp; go\" arguments=\"friday://habit?token=abc&amp;answer=open\" "
        "activationType='protocol'/>")


def test_api_endpoint_and_the_link_handler(log, monkeypatch):
    links = buttons.offer("habit", **HABIT)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")  # the API only answers local hosts
    token, _ = answer_of(links[1][1])
    assert client.post("/api/v1/notify/respond", json={"token": token, "answer": "later"}).json() == {
        "message": "Okay, not now."}
    assert client.post("/api/v1/notify/respond", json={"token": token, "answer": "later"}).status_code == 404

    sent = []
    monkeypatch.setattr(protocol_handler.urllib.request, "urlopen",
                        lambda request, timeout: sent.append(request.data) or type("R", (), {"read": lambda s: b""})())
    protocol_handler.main("friday://habit?token=abcdefghijkl&answer=open", "8000")
    protocol_handler.main("friday://habit?token=bad token!&answer=open", "8000")  # not a link FRIDAY made
    assert sent == [b'{"token": "abcdefghijkl", "answer": "open"}']
