from datetime import datetime, timedelta

import pytest

from services.proactive import attendance as att, buttons, timetable

MONDAY = datetime(2026, 9, 28, 10, 30)


@pytest.fixture(autouse=True)
def classes():
    timetable._save([{"day": "monday", "start": "08:30", "end": "10:20", "subject": "WMAD", "room": None},
                     {"day": "monday", "start": "10:40", "end": "11:35", "subject": "EVS", "room": None},
                     {"day": "monday", "start": "14:25", "end": "16:15", "subject": "DS", "room": None}])
    timetable._save_subjects(["Data Structures", "Web and Mobile App Development"])


def cmd(text, now=MONDAY):
    parsed = att.match_attendance_command(text)
    assert parsed, f"not recognised: {text}"
    return att.run(parsed, now)


def test_the_numbers():
    assert (att.can_skip(9, 10), att.to_recover(9, 10)) == (2, 0)   # 9/12 is still 75%
    assert (att.can_skip(7, 10), att.to_recover(7, 10)) == (0, 2)   # 9/12 = 75%
    assert att.status("DBMS", 7, 10) == "DBMS 7/10 (70%) — below 75%: attend the next 2 in a row to get back"
    assert att.status("DBMS", 15, 19) == "DBMS 15/19 (79%) — close to 75%"


def test_asked_once_after_class_and_the_button_records_it():
    assert [a["text"] for a in att.due_asks(MONDAY)] == ["WMAD (8:30 am–10:20 am): attended?"]
    assert att.due_asks(MONDAY + timedelta(minutes=1)) == []                                 # once
    assert att.due_asks(MONDAY.replace(hour=13)) == []                                        # EVS ended too long ago
    links = buttons.offer("attendance", date="2026-09-28", subject="WMAD", start="08:30")
    assert [label for label, _ in links] == ["Attended", "Missed"]
    token = links[1][1].split("token=")[1].split("&")[0]
    assert buttons.respond(token, "no") == "Marked WMAD missed. WMAD 0/1 (0%) — below 75%: attend the next 3 in a row to get back."


def test_voice_marking_by_short_or_full_name():
    assert cmd("I attended data structures") == "Marked DS attended. DS 1/1 (100%)."
    assert cmd("bunked evs today") == "Marked EVS missed. EVS 0/1 (0%) — below 75%: attend the next 3 in a row to get back."
    assert att.match_attendance_command("I missed the bus") is None
    assert cmd("attended all classes today") == "Marked all 3 classes today attended."
    assert cmd("my attendance") == "Attendance: WMAD 1/1 (100%); EVS 1/1 (100%); DS 1/1 (100%)."


def test_skipping_and_holidays():
    data = att.load()
    for i in range(4):
        att.record(data, MONDAY.date() - timedelta(days=7 * i), "DS", "14:25", True)
    att._save(data)
    assert cmd("how many DS classes can I skip") == "1 DS class in a row and you'd still be at 75% (4/4 now)."
    assert cmd("no college today") == "Holiday noted — no attendance questions today."
    assert att.due_asks(MONDAY) == []


def test_internal_marks_and_what_the_exam_needs():
    assert cmd("I got 18 out of 25 in DBMS CIE 1") == "Saved DBMS CIE 1: 18/25. DBMS: CIE 1 18/25 — 18/25 (72%)."
    cmd("scored 20/25 in dbms cie 2")
    assert cmd("my dbms marks") == "DBMS: CIE 1 18/25, CIE 2 20/25 — 38/50 (76%)."
    assert cmd("what do I need in the DBMS exam for an A") == (
        "About 64/100 in the DBMS exam for A (70+ overall), with internals at 38.0/50. Assumes internals 50 + exam 50.")
    assert cmd("what do I need in the DBMS exam for an O").startswith("Even 100/100")
