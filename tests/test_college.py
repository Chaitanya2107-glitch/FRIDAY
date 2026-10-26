from datetime import datetime, timedelta
from pathlib import Path

import pytest

from services.activity.log import ActivityLog
from services.automation import typing_commands
from services.files import filing
from services.proactive import buttons, college, deadlines, timetable

MONDAY = datetime(2026, 9, 28, 10, 42)


@pytest.fixture(autouse=True)
def classes(monkeypatch):
    timetable._save([{"day": "monday", "start": "10:40", "end": "11:35", "subject": "EVS", "room": None},
                     {"day": "monday", "start": "11:35", "end": "12:30", "subject": "DS", "room": None}])
    timetable._save_subjects(["Data Structures", "Environmental Science"])
    opened = []
    monkeypatch.setattr("services.automation.system_control.system.open_url", lambda url: opened.append(url) or "ok")
    monkeypatch.setattr(college.os, "startfile", lambda p: opened.append(str(p)))
    return opened


def cmd(text, now=MONDAY, log=None):
    parsed = college.match_college_command(text)
    assert parsed, f"not recognised: {text}"
    return college.run(parsed, log, now)


def test_class_links_and_joining(classes):
    assert cmd("DS class link is meet.google.com/abc-defg-hij").startswith("Saved the DS class link.")
    assert college.link_for("DS") == "https://meet.google.com/abc-defg-hij"
    assert cmd("join data structures class") == "Joining DS."
    with pytest.raises(Exception, match="I don't have a link for EVS"):
        cmd("join my class")  # EVS is on now
    assert cmd("join my class", now=MONDAY.replace(hour=11, minute=0) + timedelta(minutes=36)) == "Joining DS."
    token = buttons.offer("join", url="https://meet.google.com/x")[0][1].split("token=")[1].split("&")[0]
    assert buttons.respond(token, "join") == "Joining." and classes[-1] == "https://meet.google.com/x"


def test_study_mode_offered_once_at_class_start():
    offer = college.class_start_offer(MONDAY, active=True, mode_on=False)
    assert offer == {"subject": "EVS", "text": "EVS has started. Start study mode for EVS?"}
    assert college.class_start_offer(MONDAY, active=True, mode_on=False) is None                 # once
    assert college.class_start_offer(MONDAY.replace(hour=11, minute=36), active=False, mode_on=False) is None  # away
    assert college.class_start_offer(MONDAY.replace(hour=11, minute=36), active=True, mode_on=True) is None   # a mode on


def test_exam_countdown():
    deadlines._save([{"what": "DBMS CIE 2", "due": (MONDAY + timedelta(days=9)).isoformat(), "alerted": []},
                     {"what": "DBMS assignment", "due": (MONDAY + timedelta(days=9)).isoformat(), "alerted": []},
                     {"what": "OS quiz", "due": (MONDAY + timedelta(days=1)).isoformat(), "alerted": []}])
    assert college.exam_line(MONDAY) == "Exams: DBMS CIE 2 in 9 days."  # the quiz is in "Due soon" already


def test_syllabus_units(tmp_path):
    text = "Course: Data Structures\nUNIT-I Introduction\nArrays, stacks.\nUnit 2: Trees\nBST, AVL.\nModule III - Graphs\nBFS"
    assert college.parse_units(text) == {"1": "Introduction Arrays, stacks.", "2": "Trees BST, AVL.", "3": "Graphs BFS"}
    syllabus = tmp_path / "ds syllabus.txt"
    syllabus.write_text(text)
    assert cmd(f"data structures syllabus is in {syllabus}") == "Saved the DS syllabus: units 1, 2, 3."
    assert cmd("what's in DS unit 2") == "DS unit 2: Trees BST, AVL."


def test_revision_pack(tmp_path):
    log = ActivityLog(str(tmp_path / "a.db"))
    log._insert(at=(MONDAY - timedelta(days=1)).isoformat(), kind="web", target="www.youtube.com",
                title="Stacks in Data Structures - YouTube")
    log._insert(at=(MONDAY - timedelta(days=1)).isoformat(), kind="app", app="acrobat", title="DS notes.pdf", duration_s=3600)
    (filing.COLLEGE_DIR / "DS").mkdir(parents=True)
    (filing.COLLEGE_DIR / "DS" / "unit1.pdf").write_text("x")
    assert cmd("make a revision pack for data structures", log=log) == "Made your revision pack: DS revision pack.md."
    pack = (filing.COLLEGE_DIR / "DS" / "DS revision pack.md").read_text(encoding="utf-8")
    for line in ["## Your files\n- unit1.pdf", "## Videos you watched\n- Stacks in Data Structures",
                 "## Study time (last 4 months)\n- 1h 0m"]:
        assert line in pack


def test_assignment_starter(classes):
    deadlines._save([{"what": "DS assignment 2", "due": (MONDAY + timedelta(days=2)).isoformat(), "alerted": []}])
    assert cmd("start the DS assignment") == "Started DS assignment 2: folder ready, due Wednesday 30 Sep at 10:42 AM."
    assert (filing.COLLEGE_DIR / "DS" / "DS assignment 2").is_dir()
    assert deadlines.load()[0]["started"]
    assert college.match_college_command("start the car project") is None  # not a subject


def test_profile_and_typing_it():
    assert cmd("my USN is R24AI123").startswith("Saved your USN.")
    assert cmd("what's my usn") == "Your USN is R24AI123."
    assert typing_commands.match_typing_command("type my usn")["text"] == "R24AI123"
    assert typing_commands.match_typing_command("type my name please")["text"] != ""  # unknown: typed as said


def test_download_rename(tmp_path):
    src = tmp_path / "Unit2_notes (3).pdf"
    src.write_text("x")
    reply = filing.move(str(src), str(filing.COLLEGE_DIR / "DS"), rename=True)
    assert reply == "Moved Unit2_notes (3).pdf to College\\DS as DS - Unit 2 notes.pdf."
    assert filing.tidy_name("Data_Structures_unit1", "DS") == "Data Structures unit 1"  # names the subject already
