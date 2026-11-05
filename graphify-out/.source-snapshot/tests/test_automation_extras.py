import asyncio
import os
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from services.activity import limits
from services.activity.log import ActivityLog
from services.automation import clipboard_transforms as ct, intent, modes, system_control
from services.files import filing, installers
from services.watch import auto


# ── Clipboard transforms ──────────────────────────────────────────────────────

@pytest.fixture
def board(monkeypatch):
    state = {"text": "hello world.  this is   FRIDAY.\n\n\n\nbye  "}
    monkeypatch.setattr(ct.clipboard, "get_text", lambda: state["text"])
    monkeypatch.setattr(ct.clipboard, "set_text", lambda text: state.__setitem__("text", text))
    return state


@pytest.mark.parametrize("command, expected", [
    ("make my clipboard uppercase", "HELLO WORLD.  THIS IS   FRIDAY.\n\n\n\nBYE  "),
    ("convert the clipboard to sentence case", "Hello world.  This is   friday.\n\n\n\nBye  "),
    ("put my clipboard on one line", "hello world. this is FRIDAY. bye"),
    ("clean up my clipboard", "hello world. this is FRIDAY.\n\nbye"),
])
def test_clipboard_transforms(board, command, expected):
    result = asyncio.run(intent.try_system_action(command, "openai"))
    assert result.success and board["text"] == expected


def test_paste_as_plain_text_pastes_into_the_app_in_front(board):
    result = asyncio.run(intent.try_system_action("paste as plain text", "openai"))
    assert result.keyboard == ({"keys": "ctrl+v"},)


def test_count_and_what_is_left_alone(board):
    assert asyncio.run(intent.try_system_action("count the words in my clipboard", "openai")).message == \
        "6 words, 40 characters."
    for other in ("read my clipboard", "clear clipboard history", "uppercase"):
        assert ct.match_clipboard_transform(other) is None


# ── Installers ────────────────────────────────────────────────────────────────

def _file(folder, name, size=2_000_000, age_hours=48):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"x" * size)
    old = time.time() - age_hours * 3600
    os.utime(path, (old, old))
    return path


def test_old_installers_are_binned_after_a_yes(monkeypatch):
    _file(installers.DOWNLOADS, "chrome_setup.exe")
    _file(installers.DOWNLOADS, "python.msi", size=5_000_000)
    _file(installers.DOWNLOADS, "fresh.exe", age_hours=1)  # might be about to run
    _file(installers.DOWNLOADS, "notes.pdf")
    binned = []
    monkeypatch.setattr(installers, "_recycle", binned.extend)
    ask = asyncio.run(intent.try_system_action("delete my installers", "openai"))
    assert ask.message == "Move 2 installers (7 MB): python.msi, chrome_setup.exe to the Recycle Bin? Say yes or no."
    assert binned == []
    done = asyncio.run(intent.try_system_action("yes", "openai"))
    assert done.message == "Moved 2 installers (7 MB) to the Recycle Bin."
    assert sorted(p.name for p in binned) == ["chrome_setup.exe", "python.msi"]


def test_no_installers_means_no_question():
    result = asyncio.run(intent.try_system_action("clean up old installers", "openai"))
    assert result.message == "No old installers in Downloads." and not intent.is_awaiting_confirmation()


# ── Screenshots ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("context", ["class", "study", "neither"])
def test_screenshots_stay_in_screenshots_folder(context, tmp_path, monkeypatch):
    screenshots, downloads = tmp_path / "Screenshots", tmp_path / "Downloads"
    screenshots.mkdir()
    downloads.mkdir()
    monkeypatch.setattr(system_control, "SCREENSHOT_DIR", screenshots)
    monkeypatch.setattr(system_control.system, "last_screenshot", None)
    monkeypatch.setattr(system_control.ImageGrab, "grab", lambda **kw:
                        SimpleNamespace(save=lambda path: path.write_bytes(b"png")))
    monkeypatch.setattr(auto, "DOWNLOADS", downloads)
    monkeypatch.setattr(filing.timetable, "classes_for_date", lambda day: [
        {"start": "00:00", "end": "23:59", "subject": "DBMS"}] if context == "class" else [])
    monkeypatch.setattr(modes, "active", lambda:
                        {"name": "study", "subject": "Finance"} if context == "study" else None)
    monkeypatch.setattr(auto, "read_load", lambda: (0, None, False))
    monkeypatch.setattr(auto.asked, "check", lambda *a: [])
    announced, toasts = [], []
    monkeypatch.setattr(auto, "announce", lambda path, slow: announced.append(path))
    monkeypatch.setattr("services.reminders.service.show_toast", lambda *a: toasts.append(a))
    ticks = 0

    async def next_tick(seconds):
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            system_control.system.take_screenshot()
            (screenshots / "Screenshot.png").write_bytes(b"external png")
            (downloads / "notes.txt").write_text("notes")
        else:
            raise asyncio.CancelledError

    monkeypatch.setattr(auto.asyncio, "sleep", next_tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(auto.run_watches())

    assert system_control.system.last_screenshot.parent == screenshots
    assert system_control.system.last_screenshot.read_bytes() == b"png"
    assert (screenshots / "Screenshot.png").read_bytes() == b"external png"
    assert not filing.COLLEGE_DIR.exists() and toasts == []
    assert announced == [downloads / "notes.txt"]


# ── App limits ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("limit valorant to 2 hours a day", {"action": "set_limit", "app": "valorant", "minutes": 120}),
    ("set a daily limit of 90 minutes for Minecraft", {"action": "set_limit", "app": "minecraft", "minutes": 90}),
    ("remove the limit on valorant", {"action": "remove_limit", "app": "valorant"}),
    ("what are my app limits", {"action": "list_limits"}),
    ("limit", None),
])
def test_limit_commands(text, expected):
    match = limits.match_limit_command(text)
    assert (match and {k: v for k, v in match.items() if k != "type"}) == expected


def test_limit_warnings_once_each(tmp_path):
    limits.run({"action": "set_limit", "app": "valorant", "minutes": 60})
    log = ActivityLog(str(tmp_path / "activity.db"))
    start = datetime(2026, 9, 30, 18, 0)
    log.observe("valorant-win64-shipping", now=start, title="VALORANT")
    log.title_since = start

    def at(minute):
        return limits.due_alerts(log, datetime(2026, 9, 30, 18 + minute // 60, minute % 60))
    assert at(30) == []
    assert at(52) == ["10 minutes of valorant left today."]
    assert at(55) == []  # already told
    assert at(61) == ["That's your 1h of valorant for today."]
    assert at(95) == ["30m over your valorant limit today."]
    assert limits.run({"action": "list_limits"}) == "Daily limits: valorant 1h."
