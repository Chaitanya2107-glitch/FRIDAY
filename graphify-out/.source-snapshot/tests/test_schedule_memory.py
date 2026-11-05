import asyncio
from datetime import datetime, timedelta

import pytest

from services.automation import intent
from services.memory import semantic
from services.proactive import attendance, college, timetable

MONDAY = datetime(2026, 10, 12, 9, 56)
FACT = "for the next 4 days theres only placement training and theres no classes in my schedule"


@pytest.fixture
def saved(monkeypatch):
    memory = semantic.semantic_memory
    timetable._save([dict(day=day, start="09:00", end="10:00", subject="DBMS", room="204")
                     for day in timetable.DAYS])

    def save(text=FACT, noted=MONDAY):
        with memory._connect() as db:
            db.execute("INSERT INTO memories (text, vector, source, created_at) VALUES (?, ?, 'told', ?)",
                       (text, b"\0" * 16, noted.isoformat()))
        memory._cache = None

    save()
    return save


def test_saved_four_day_fact_overrides_all_class_surfaces(saved):
    wednesday = MONDAY + timedelta(days=2)
    assert timetable.due_warnings(wednesday.replace(hour=8, minute=55)) == []
    assert college.class_start_offer(wednesday.replace(hour=9, minute=2), True, False) is None
    assert attendance.due_asks(wednesday.replace(hour=10, minute=5)) == []
    assert timetable.today_line(wednesday).startswith("No classes today")
    assert timetable.run({"action": "show_classes", "day": "tomorrow"}, wednesday).startswith("No classes tomorrow")
    assert "Today: no classes" in timetable.prompt_line(wednesday)
    assert "Tomorrow: no classes" in timetable.prompt_line(wednesday)
    assert "Friday" in timetable.next_class(wednesday)
    assert len(timetable.load()) == 7


def test_date_window_is_anchored_to_when_fact_was_saved_and_expires(saved):
    thursday = MONDAY + timedelta(days=3)
    friday = MONDAY + timedelta(days=4)
    assert timetable.due_warnings(thursday.replace(hour=8, minute=55)) == []
    assert len(timetable.due_warnings(friday.replace(hour=8, minute=55))) == 1
    assert len(attendance.due_asks(friday.replace(hour=10, minute=5))) == 1


def test_newer_resume_fact_restores_classes_from_that_date(saved):
    saved("actually my classes resume tomorrow", MONDAY + timedelta(days=2))
    assert timetable.due_warnings((MONDAY + timedelta(days=2)).replace(hour=8, minute=55)) == []
    assert len(timetable.due_warnings((MONDAY + timedelta(days=3)).replace(hour=8, minute=55))) == 1


def test_old_attendance_button_cannot_mark_a_cancelled_class(saved):
    about = dict(date="2026-10-14", subject="DBMS", start="09:00")
    reply = attendance.answer(about, "no")
    assert "cancel" in reply.lower()
    assert attendance.load()["records"] == []


def test_cancelled_sessions_do_not_lower_attendance_without_deleting_records(saved):
    data = attendance.load()
    attendance.record(data, MONDAY.date(), "DBMS", "09:00", False)
    attendance.record(data, (MONDAY + timedelta(days=4)).date(), "DBMS", "09:00", True)
    assert attendance.counts(data) == {"DBMS": (1, 1)}
    assert len(data["records"]) == 2


def test_ordinary_schedule_statement_is_saved_before_an_ai_reply(monkeypatch):
    # The class override must not depend on a working provider or embedding model.
    async def no_ai(*args, **kwargs):
        pytest.fail("an explicit dated class fact reached the command AI")

    monkeypatch.setattr(intent, "get_provider", lambda *a, **k: pytest.fail("schedule facts should work offline"))
    text = "I have placement training for the next 4 days so I won't have classes"
    result = asyncio.run(intent.try_system_action(text, "openrouter"))
    assert result is not None and result.success
    assert "class" in result.message.lower() and "2026-" in result.message


@pytest.mark.parametrize("text,start,end,subject", [
    ("I won't have classes for four days starting Monday", "2026-10-19", "2026-10-22", ""),
    ("No classes for 4 days from 2026-10-19", "2026-10-19", "2026-10-22", ""),
    ("No DBMS classes tomorrow", "2026-10-15", "2026-10-15", "DBMS"),
    ("No classes from Monday to Thursday", "2026-10-19", "2026-10-22", ""),
])
def test_explicit_start_dates_and_subject_scope(text, start, end, subject):
    from services.memory import schedule
    fact = schedule.parse(text, datetime(2026, 10, 14, 11))
    assert fact and (fact.start.isoformat(), fact.end.isoformat(), fact.subject) == (start, end, subject)


@pytest.mark.parametrize("text", [
    "What if I won't have classes for 4 days?", "My friend has no classes for 4 days",
    "Type no classes for 4 days", "I might have no classes tomorrow if training is confirmed",
])
def test_hypothetical_and_quoted_statements_do_not_change_schedule(text):
    from services.memory import schedule
    assert schedule.parse(text, MONDAY) is None


def test_forgetting_the_training_fact_restores_schedule_and_memory_list(saved):
    from services.memory import schedule
    schedule.capture("I have no classes tomorrow because of placement training", MONDAY)
    assert any("placement training" in fact for fact, _ in semantic.semantic_memory.all())
    result = semantic.run_memory_command({"action": "forget_memory", "text": "placement training"})
    assert result.startswith("Forgot:")
    assert schedule.facts() == []
    assert len(timetable.due_warnings((MONDAY + timedelta(days=2)).replace(hour=8, minute=55))) == 1
