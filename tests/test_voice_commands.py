import asyncio
import json
from datetime import datetime

import pytest

from services.automation import intent
from services.voice import voice_commands as vc, wake
from services.voice import tts as tts_module
from services.voice.tts import tts


@pytest.mark.parametrize("text, expected", [
    ("read this", {"action": "read_aloud"}),
    ("read it out loud", {"action": "read_aloud"}),
    ("read the selection", {"action": "read_aloud"}),
    ("read aloud", {"action": "read_aloud"}),
    ("read my clipboard", None),  # shows it (device_commands.py)
    ("stop reading", {"action": "stop_speaking"}),
    ("talk faster", {"action": "speech_speed", "change": 15}),
    ("speak a bit slower", {"action": "speech_speed", "change": -15}),
    ("slow down", {"action": "speech_speed", "change": -15}),
    ("normal speed", {"action": "speech_speed", "change": None}),
    ("how many false wakes", {"action": "wake_stats"}),
    ("read my notes", None),
    ("read", None),
    ("read this book", None),
])
def test_voice_commands(text, expected):
    match = vc.match_voice_command(text)
    assert (match and {k: v for k, v in match.items() if k != "type"}) == expected


@pytest.fixture
def clipboard(monkeypatch):
    state = {"text": "old copy", "seq": 1, "pressed": [], "copies": True}

    def press(keys):
        state["pressed"].append(keys)
        if state["copies"]:
            state["text"], state["seq"] = "The  selected\ntext.", state["seq"] + 1

    monkeypatch.setattr(vc, "_bar_in_front", lambda: False)
    monkeypatch.setattr(vc.keyboard, "press_keys", press)
    monkeypatch.setattr(vc.clipboard, "sequence_number", lambda: state["seq"])
    monkeypatch.setattr(vc.clipboard, "get_text", lambda: state["text"])
    monkeypatch.setattr(vc.clipboard, "is_private", lambda: False)
    monkeypatch.setattr(vc, "COPY_WAIT_SECONDS", 0.1)
    return state


def test_read_this_copies_the_selection_and_speaks_it(clipboard):
    result = vc.read_aloud()
    assert clipboard["pressed"] == ["ctrl+c"]
    assert result.success and result.speech == "The selected text." and result.message.startswith("Reading it out (3 words)")


def test_nothing_selected_is_said_not_the_old_clipboard(clipboard):
    clipboard["copies"] = False
    result = vc.read_aloud()
    assert not result.success and result.speech is None and "Nothing's selected" in result.message


def test_from_the_command_bar_it_reads_what_was_copied(clipboard, monkeypatch):
    monkeypatch.setattr(vc, "_bar_in_front", lambda: True)
    assert vc.read_aloud().speech == "old copy" and clipboard["pressed"] == []


def test_private_clipboard_is_never_read(clipboard, monkeypatch):
    monkeypatch.setattr(vc.clipboard, "is_private", lambda: True)
    assert not vc.read_aloud().success


def test_reading_aloud_is_refused_over_telegram(clipboard):
    token = intent.remote_request.set(True)
    try:
        result = asyncio.run(intent.try_system_action("read this", "openai"))
    finally:
        intent.remote_request.reset(token)
    assert not result.success and clipboard["pressed"] == []


def test_speed_steps_are_kept_and_capped():
    assert vc.set_speed(15) == "Okay — talking faster now (15% above normal)."
    assert json.loads(tts_module.SPEED_PATH.read_text()) == {"rate": 15}
    assert tts.rate == 15 and tts._load_rate() == 15  # survives a restart
    tts.set_rate(100)
    assert vc.set_speed(15) == "That's as fast as I go."
    assert vc.set_speed(None) == "Okay, back to normal speed." and tts.rate == 0
    assert vc.set_speed(-15) == "Okay — talking slower now (15% below normal)."


def test_other_speeds_are_other_cached_audio():
    tts._remember("Muted.", b"normal")
    tts.set_rate(30)
    assert tts._cached("Muted.") is None
    tts.set_rate(0)
    assert tts._cached("Muted.") == b"normal"


def test_wake_stats_count_mistakes():
    assert "hasn't woken me" in wake.stats()
    now = datetime(2026, 9, 30, 12)
    wake.record(False, now=now)
    wake.record(True, now=now)
    wake.record(True, now=datetime(2026, 9, 1))  # too old
    assert wake.stats(now) == 'In the last 7 days "Hey Friday" woke me 2 times; 1 was a mistake (50%).'
    assert "heard" not in wake.LOG_PATH.read_text()  # never what was said
