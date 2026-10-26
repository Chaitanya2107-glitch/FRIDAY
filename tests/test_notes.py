import asyncio
from datetime import date, datetime

import pytest

from services.activity import journal
from services.activity.log import ActivityLog
from services.automation import intent
from services.automation.system_control import AutomationError
from services.memory import notes
from services.proactive import briefing


@pytest.mark.parametrize("text, expected", [
    ("note buy a new charger", {"action": "add_note", "text": "buy a new charger"}),
    ("Idea: FRIDAY could read PDFs aloud", {"action": "add_note", "text": "FRIDAY could read PDFs aloud"}),
    ("make a note that the lab moved to room 204", {"action": "add_note", "text": "the lab moved to room 204"}),
    ("Note, call Ravi", {"action": "add_note", "text": "call Ravi"}),
    ("read my notes", {"action": "list_notes"}),
    ("delete note 2", {"action": "delete_note", "number": 2}),
    ("clear my notes", {"action": "clear_notes"}),
    ("notepad", None),
    ("open notes", None),  # still opens Notepad
    ("ideas for dinner", None),
])
def test_note_commands(text, expected):
    match = notes.match_note_command(text)
    assert (match and {k: v for k, v in match.items() if k != "type"}) == expected


def test_add_list_delete_clear():
    assert notes.add("buy milk", datetime(2026, 9, 29, 9, 5)) == "Noted. You have 1 note."
    notes.add("call Ravi", datetime(2026, 9, 29, 14, 30))
    assert notes.list_message() == "1. buy milk (29 Sep, 09:05)\n2. call Ravi (29 Sep, 14:30)"
    assert notes.delete(1) == "Deleted: buy milk"
    with pytest.raises(AutomationError, match="There's no note 5"):
        notes.delete(5)
    assert notes.clear() == "Cleared 1 note."
    assert notes.list_message() == "No notes."


def test_notes_through_the_command_path_keep_their_case():
    result = asyncio.run(intent.try_system_action("hey friday, note Ask Prof. Rao about the LAB", "openai"))
    assert result.success and result.message == "Noted. You have 1 note."
    assert notes.load()[0]["text"] == "Ask Prof. Rao about the LAB"


def test_a_note_is_never_a_web_or_screen_question():
    assert notes.is_note("note look up cheap flights to Goa")
    assert not notes.is_note("look up cheap flights to Goa")


def test_notes_in_the_journal_and_briefing(tmp_path):
    notes.add("buy milk", datetime(2026, 9, 29, 9, 5))
    notes.add("call Ravi", datetime(2026, 9, 28, 20, 0))
    text = journal.build(date(2026, 9, 29), ActivityLog(str(tmp_path / "empty.db")))
    assert "## Notes\n- 09:05 — buy milk" in text and "call Ravi" not in text
    for extra in ("a", "b"):
        notes.add(extra)
    assert notes.briefing_line() == "You have 4 notes: buy milk; call Ravi; a; and 1 more."


def test_briefing_mentions_notes(monkeypatch):
    monkeypatch.setattr(briefing, "weather", lambda city=None: "")
    monkeypatch.setattr(briefing, "_system", lambda: "")
    monkeypatch.setattr(briefing, "_yesterday", lambda now: "")
    monkeypatch.setattr(briefing, "_classes_today", lambda now: "")
    notes.add("buy milk")
    assert "You have 1 note: buy milk." in briefing.build(datetime(2026, 9, 29, 8, 0))


def test_journal_entries_go_only_into_that_days_journal(tmp_path):
    result = asyncio.run(intent.try_system_action("journal: the viva went well", "openai"))
    assert result.success and result.message == "Added to today's journal."
    assert notes.is_note("dear diary, look up why I'm so tired")  # saved, not searched
    notes.add_diary("slept badly", datetime(2026, 9, 29, 23, 40))
    text = journal.build(date(2026, 9, 29), ActivityLog(str(tmp_path / "empty.db")))
    assert "## Diary\n- 23:40 — slept badly" in text
    assert notes.load() == [] and notes.briefing_line() == ""  # never in the notes inbox
