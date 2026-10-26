from datetime import datetime, timedelta

import train_friday
from services.mind import thoughts, wonder, talk
from services.mind.reviews import reviews


def test_inbox_keeps_all_custom_questions_and_excludes_previously_asked():
    questions = [f"What do you want from project {i}?" for i in range(45)]
    wonder.add(questions)
    wonder.mark_asked(questions[0], now=1)
    rows = train_friday.interview_questions("personal")
    assert [r["question"] for r in rows[:44]] == questions[1:]
    assert len(rows) > 30


def test_inbox_contains_older_unasked_observations_and_day_questions():
    thought = thoughts.add("unknown", "app:old", {"name": "old", "pattern": "old-pattern"},
                           0.8, datetime.now() - timedelta(days=2))
    rows = train_friday.interview_questions()
    observation = next(r for r in rows if r.get("thought") == thought)
    assert "old" in observation["question"]
    assert observation["pattern"] == "old-pattern"
    assert any(r["topic"] == "day" and "away from the laptop" in r["question"] for r in rows)


def test_session_is_unlimited_by_default_and_preserves_live_pending(monkeypatch):
    questions = [f"What do you like about hobby {i}?" for i in range(35)]
    wonder.add(questions)
    pending = {"question": "Live question", "where": "asked", "at": 1}
    talk._save({"pending": pending})
    answers = iter(["An answer"] * 35 + ["/stop", "yes"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert train_friday.main(["session", "--topic", "personal"]) == 0
    assert len(reviews.active_lessons()) == 35
    assert talk.load()["pending"] == pending
    assert wonder.answer_for(questions[-1]) == "An answer"


def test_skipping_does_not_hide_question_and_draft_answer_does(monkeypatch):
    question = "What do you like about your current project?"
    wonder.add([question])
    answers = iter(["", "/stop"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    train_friday.session(topic="personal")
    assert train_friday.interview_questions("personal")[0]["question"] == question
    answers = iter(["Learning", "/stop", "no"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    train_friday.session(topic="personal")
    assert question not in [r["question"] for r in train_friday.interview_questions("personal")]
    assert reviews.list()[0]["live_answer"] == "Learning"
    assert not reviews.learned()


def test_day_answer_survives_interrupt_and_does_not_repeat_that_day(monkeypatch):
    calls = 0
    def answer(prompt):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "Studied at college"
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", answer)
    first = train_friday.interview_questions("day")[0]["question"]
    assert train_friday.main(["session", "--topic", "day"]) == 0
    assert reviews.list()[0]["live_answer"] == "Studied at college"
    assert first not in [r["question"] for r in train_friday.interview_questions("day")]


def test_questions_command_only_lists_and_never_marks_questions_asked(capsys):
    wonder.add(["What does your new project mean to you?"])
    assert train_friday.main(["questions", "--topic", "personal"]) == 0
    assert "new project" in capsys.readouterr().out
    assert not reviews.question_states()


def test_day_lessons_are_dated_and_long_answers_stay_complete_drafts(monkeypatch):
    answers = iter(["Good day", "yes"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    train_friday.session(count=1, topic="day")
    lesson = reviews.learned()[0]
    assert datetime.now().date().isoformat() in lesson["teaching"]
    assert "Good day" in lesson["teaching"]
    long_answer = "A detailed account. " * 100
    answers = iter([long_answer])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    train_friday.session(count=1, topic="day")
    draft = reviews.list()[0]
    assert draft["live_answer"] == long_answer.strip()
    assert draft["teaching"] == ""


def test_explicit_count_can_exceed_thirty_and_must_be_positive(monkeypatch):
    answers = iter([""] * 40)
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert train_friday.main(["session", "--topic", "personal", "--count", "40"]) == 0
    assert train_friday.main(["session", "--count", "0"]) == 1


def test_live_day_answers_without_day_metadata_do_not_hide_future_checkins():
    first = train_friday.interview_questions("day")[0]["question"]
    yesterday = datetime.now() - timedelta(days=1)
    item = reviews.capture("question", first, {"where": "evening"}, at=yesterday.timestamp())
    reviews.answer(item, "Went to college", "answered")
    assert first in [r["question"] for r in train_friday.interview_questions("day")]


def test_interview_never_calls_a_model(monkeypatch):
    async def forbidden(*a, **kw):
        raise AssertionError("Local interview called a model")
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    answers = iter(["Went to college", "yes"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert train_friday.main(["session", "--topic", "day", "--count", "1"]) == 0
