from datetime import date, datetime

import pytest

from services.activity import journal
from services.activity.log import ActivityLog
from services.automation.system_control import AutomationError

DAY = date(2026, 9, 28)


def at(hour, minute=0):
    return datetime(2026, 9, 28, hour, minute).isoformat()


@pytest.fixture
def log(tmp_path):
    log = ActivityLog(str(tmp_path / "a.db"))
    add = log._insert
    add(at=at(9), kind="app", app="windowsterminal", title="✳ Build next", duration_s=3600, project="catjang")
    add(at=at(10), kind="app", app="chrome", title="How B-Trees Work - YouTube - Google Chrome", duration_s=1200)
    add(at=at(10, 1), kind="web", target="www.youtube.com", title="(3) How B-Trees Work - YouTube")
    add(at=at(11), kind="web", target="www.google.com", title="dbms normalization - Google Search")
    add(at=at(12), kind="app", app="spotify", title="Arijit Singh - Tose Naina", duration_s=300)
    add(at=at(12, 5), kind="app", app="spotify", title="Spotify Premium", duration_s=120)
    add(at=at(13), kind="file", target="DBMS Unit 2.pdf")
    add(at=at(13, 1), kind="file", target="ms-screenclip---source=PrintScreen")
    return log


def test_the_days_journal(log, monkeypatch):
    monkeypatch.setattr(journal, "_commits", lambda day: {"catjang": ["Add cat sprites", "Fix jump"]})
    monkeypatch.setattr(journal, "_classes", lambda day: ["10:00 am DBMS (204)"])
    text = journal.build(DAY, log)
    assert text.startswith("# Monday, 28 September 2026\n\n**Active:** 1h 27m — project 1h 0m, entertainment 20m, music 7m")
    for line in ["## Projects\n- catjang — 1h 0m (2 commits)",
                 "## Commits\n- catjang: Add cat sprites\n- catjang: Fix jump",
                 "## Classes\n- 10:00 am DBMS (204)",
                 "## Watched\n- How B-Trees Work (youtube.com)",
                 "## Listened to\n- Arijit Singh - Tose Naina",
                 "## Searched for\n- dbms normalization (google.com)",
                 "## Files opened\n- DBMS Unit 2.pdf",
                 "## Apps\n- windowsterminal 1h 0m, chrome 20m, spotify 7m"]:
        assert line in text
    assert "screenclip" not in text and "Spotify Premium" not in text


def test_an_empty_day(tmp_path):
    empty = ActivityLog(str(tmp_path / "e.db"))
    assert "_Nothing recorded for this day._" in journal.build(DAY, empty)
    assert journal.evening_note(DAY, empty) is None


def test_evening_note_writes_the_file(log, monkeypatch):
    monkeypatch.setattr(journal, "_commits", lambda day: {})
    note = journal.evening_note(DAY, log)
    assert note.startswith("Today's journal is saved — 1h 27m")
    assert journal.journal_path(DAY).read_text(encoding="utf-8").startswith("# Monday, 28 September 2026")


def test_open_writes_todays_if_missing(log, monkeypatch):
    opened = []
    monkeypatch.setattr(journal.os, "startfile", opened.append)
    monkeypatch.setattr(journal, "_commits", lambda day: {})
    assert journal.run({"action": "open_journal", "day": "today"}, log, today=DAY) == \
        "Opening your journal for Monday, 28 September."
    assert opened == [journal.journal_path(DAY)]
    with pytest.raises(AutomationError, match="no journal for Tuesday"):
        journal.run({"action": "open_journal", "day": "tuesday"}, log, today=DAY)


@pytest.mark.parametrize("text, expected", [
    ("write my journal", {"action": "write_journal"}),
    ("open my journal", {"action": "open_journal", "day": "today"}),
    ("open yesterday's journal", {"action": "open_journal", "day": "yesterday"}),
    ("show my journal for last friday", {"action": "open_journal", "day": "friday"}),
    ("what's the weather", None),
])
def test_commands(text, expected):
    match = journal.match_journal_command(text)
    assert (match and {k: v for k, v in match.items() if k != "type"}) == expected
