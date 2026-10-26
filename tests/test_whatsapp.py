import asyncio

import pytest

from services.automation import actions, intent, whatsapp
from services.automation.system_control import AutomationError


@pytest.fixture
def contacts():
    whatsapp.run_contacts({"action": "save_contact", "name": "mom", "number": "98765 43210"})
    whatsapp.run_contacts({"action": "save_contact", "name": "rahul sharma", "number": "+44 7700 900123"})


def match(text, original=None):
    m = whatsapp.match_whatsapp_command(text, original)
    return m and {k: v for k, v in m.items() if k != "type"}


@pytest.mark.parametrize("text, expected", [
    ("message mom on whatsapp: I'll be late", {"contact": "mom", "text": "I'll be late"}),
    ("whatsapp mom I'll be late", {"contact": "mom", "text": "I'll be late"}),
    ("send a whatsapp to mom saying dinner is ready", {"contact": "mom", "text": "dinner is ready"}),
    ("send a whatsapp message to my mom that I reached", {"contact": "mom", "text": "I reached"}),
    ("text mom I'm home", {"contact": "mom", "text": "I'm home"}),                 # a saved name: no "whatsapp" needed
    ("tell rahul sharma on whatsapp that the meeting moved", {"contact": "rahul sharma", "text": "the meeting moved"}),
    ("whatsapp 9876543210 hi there", {"contact": "9876543210", "text": "hi there"}),
    ("message priya on whatsapp: see you", {"contact": "priya", "text": "see you"}),  # unknown: asks for the number later
])
def test_send_commands(contacts, text, expected):
    assert match(text) == {"action": "send_whatsapp", **expected}


@pytest.mark.parametrize("text", [
    "tell me a joke", "message", "text priya hello",   # not saved and no "whatsapp": not a message
    "open whatsapp", "what's the time",
])
def test_not_whatsapp_messages(contacts, text):
    assert match(text) is None


def test_the_message_keeps_its_punctuation(contacts):
    assert match("message mom on whatsapp are you coming", "Hey Friday, message mom on WhatsApp: are you coming?")[
        "text"] == "are you coming?"


def test_contacts(contacts):
    assert whatsapp.load() == {"mom": "919876543210", "rahul sharma": "447700900123"}
    assert match("save dad's number as 091234 56789") == {"action": "save_contact", "name": "dad", "number": "091234 56789"}
    assert whatsapp.run_contacts(match("save dad's number as 091234 56789")) == (
        'Saved Dad: +919123456789. Say "message dad on WhatsApp: …" to send one.')
    assert match("list my contacts") == {"action": "list_contacts"}
    assert whatsapp.run_contacts(match("remove contact dad")) == "Removed Dad from your contacts."
    with pytest.raises(AutomationError, match="doesn't look like a phone number"):
        whatsapp.run_contacts({"action": "save_contact", "name": "x", "number": "12"})


def test_asks_first_and_sends_only_on_yes(contacts, monkeypatch):
    opened, pressed = [], []
    monkeypatch.setattr(whatsapp.os, "startfile", opened.append)
    monkeypatch.setattr(whatsapp.keyboard, "press_keys", pressed.append)
    monkeypatch.setattr(whatsapp.time, "sleep", lambda s: None)
    monkeypatch.setattr(actions, "foreground_app", lambda: "whatsapp.root")  # actions.py runs the command

    question = asyncio.run(intent.try_system_action("message mom on whatsapp: I'll be late", "openrouter"))
    assert question.message == 'Send "I\'ll be late" to Mom on WhatsApp? Reply "yes" to send or "no" to cancel.'
    assert intent.is_awaiting_confirmation() and opened == []  # nothing sent yet

    sent = asyncio.run(intent.try_system_action("yes", "openrouter"))
    assert sent.message == "Sent to Mom on WhatsApp."
    assert opened == ["whatsapp://send?phone=919876543210&text=I%27ll%20be%20late"] and pressed == ["enter"]


def test_no_cancels(contacts, monkeypatch):
    asyncio.run(intent.try_system_action("whatsapp mom hi", "openrouter"))
    assert asyncio.run(intent.try_system_action("no", "openrouter")).message == "Okay, cancelled. Nothing was changed."


def test_enter_is_never_pressed_outside_whatsapp(contacts, monkeypatch):
    pressed = []
    monkeypatch.setattr(whatsapp.os, "startfile", lambda url: None)
    monkeypatch.setattr(whatsapp.keyboard, "press_keys", pressed.append)
    monkeypatch.setattr(whatsapp.time, "sleep", lambda s: None)
    monotonic = iter(range(0, 100))
    monkeypatch.setattr(whatsapp.time, "monotonic", lambda: next(monotonic))
    reply = whatsapp.send({"contact": "mom", "text": "hi"}, lambda: "windowsterminal")  # WhatsApp never came up
    assert pressed == [] and reply.startswith("I opened your chat with Mom with the message typed in")


def test_unknown_name_asks_for_the_number(contacts):
    with pytest.raises(AutomationError, match="I don't have a number for priya"):
        whatsapp.confirmation({"contact": "priya", "text": "hi"})
