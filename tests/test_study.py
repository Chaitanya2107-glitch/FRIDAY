from datetime import date, datetime

import pytest

from services.activity import journal, study, weekly
from services.activity.log import ActivityLog
from services.automation import modes
from services.proactive import timetable

NOW = datetime(2026, 9, 30, 20, 0)  # a Wednesday


def at(day, hour):
    return datetime(2026, 9, day, hour).isoformat()


@pytest.fixture
def log(tmp_path):
    timetable._save([{"day": "monday", "start": "09:00", "end": "10:00", "subject": "DBMS", "room": None},
                     {"day": "monday", "start": "10:00", "end": "11:00", "subject": "DS", "room": None}])
    timetable._save_subjects(["Principles of Artificial Intelligence", "Data Structures"])  # the second is DS's full name
    log = ActivityLog(str(tmp_path / "a.db"))
    add = log._insert
    add(at=at(30, 9), kind="app", app="acrobat", title="DBMS Unit 2.pdf - Adobe Acrobat", duration_s=3600)
    add(at=at(30, 10), kind="app", app="chrome", title="Data Structures - Stacks - YouTube - Google Chrome", duration_s=1200)
    add(at=at(30, 11), kind="app", app="code", title="lab3.py - Visual Studio Code", duration_s=1800, subject="DS")
    add(at=at(30, 12), kind="app", app="whatsapp", title="WhatsApp", duration_s=600, subject="DS")  # chat: not study
    add(at=at(30, 13), kind="app", app="chrome", title="PAI notes - Google Chrome", duration_s=900)
    add(at=at(30, 14), kind="app", app="chrome", title="Valorant patch notes - Google Chrome", duration_s=900)
    add(at=at(29, 9), kind="app", app="acrobat", title="dbms er diagrams.pdf", duration_s=1800)
    add(at=at(22, 9), kind="app", app="acrobat", title="dbms er diagrams.pdf", duration_s=600)  # last week
    return log


def ask(log, text):
    parsed = study.match_study_command(text)
    assert parsed, f"not recognised: {text}"
    return study.run(parsed, log, NOW)


def test_titles_and_study_mode_count_per_subject(log):
    assert ask(log, "study hours today") == \
        "Study time today: DBMS 1h 0m, DS 50m, Principles of Artificial Intelligence 15m — 2h 5m in all."


def test_one_subject_by_short_or_full_name(log):
    assert ask(log, "how long did I study DBMS this week") == "You studied DBMS for 1h 30m this week."
    assert ask(log, "how much did I study data structures today") == "You studied DS for 50m today."
    assert ask(log, "how long did I study d b m s yesterday") == "You studied DBMS for 30m yesterday."
    assert ask(log, "how long did I study OOPP today") == "You haven't studied OOPP today."


def test_a_full_name_is_an_alias_not_another_subject(log):
    assert timetable.subjects() == ["DBMS", "DS", "Principles of Artificial Intelligence"]
    assert timetable.aliases("DS") == ["DS", "Data Structures"]
    assert timetable.mentions_subject("Data Structures notes.pdf", timetable.aliases("DS"))


@pytest.mark.parametrize("short, full, expected", [
    ("DS", "Data Structures", True), ("DBMS", "Database Management Systems", True),
    ("EVS", "Environmental Science", True), ("OOPP", "Object Oriented Programming with Python", True),
    ("DMGT", "Discrete Mathematics and Graph Theory", True), ("PE", "Professional Ethics", True),
    ("DS", "Database Management Systems", False), ("PAI", "Professional Ethics", False),
    ("DBMS", "Data", False), ("UHV", "Universal Human Values Extra", False),
])
def test_abbreviations(short, full, expected):
    assert timetable.abbreviates(short, full) is expected


def test_commands():
    assert study.match_study_command("my study time last week")["subject"] == ""
    assert study.match_study_command("how many hours did i study for pai")["question"]
    assert study.match_study_command("what's the weather") is None


def test_study_mode_remembers_the_subject(log):
    assert modes.match_mode_command("start study mode for data structures")["subject"] == "data structures"
    assert modes.match_mode_command("start study mode")["subject"] == ""
    modes.begin("study", None, "data structures")
    assert modes.active()["subject"] == "DS"
    assert modes.run({"action": "mode_status"}) == "You're in study mode for DS."


def test_journal_and_week_have_a_study_section(log, monkeypatch):
    monkeypatch.setattr(journal, "_commits", lambda day: {})
    monkeypatch.setattr(weekly, "_shipped", lambda monday: {})
    assert "## Study\n- DBMS 1h 0m, DS 50m, Principles of Artificial Intelligence 15m" in journal.build(date(2026, 9, 30), log)
    week = weekly.build(date(2026, 9, 28), log)
    assert "## Study\n- DBMS 1h 30m (+1h 20m)\n- DS 50m (+50m)" in week


def test_media_playing_in_front_is_not_idle(tmp_path, monkeypatch):
    from services.activity import log as log_module

    live = ActivityLog(str(tmp_path / "b.db"))
    monkeypatch.setattr(log_module, "foreground_window", lambda: ("chrome", "Lecture 5 - YouTube"))
    monkeypatch.setattr(log_module, "foreground_ids", lambda: (1, 2))
    monkeypatch.setattr(log_module, "idle_seconds", lambda: 900)
    monkeypatch.setattr(log_module, "media_playing_in", lambda app: app == "chrome")
    live.sample(tick=1)
    assert live.app == "chrome"
    monkeypatch.setattr(log_module, "media_playing_in", lambda app: False)
    live.sample(tick=1)
    assert live.app is None
