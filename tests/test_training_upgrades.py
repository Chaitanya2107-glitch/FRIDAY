import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import config
from interfaces.api.app import create_app
from interfaces.api.routes import chat, voice
from services.mind import replies, reviews as review_module, training, wonder, evening, talk
from services.mind.reviews import reviews, ReviewStore


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", False)
    monkeypatch.setattr(config, "AI_KNOWLEDGE_ENABLED", False)


def apply(question, teaching="", preferred="", kind="example"):
    item = reviews.capture(kind, question, {})
    reviews.review(item, teaching=teaching, preferred=preferred, approve=True)
    reviews.train(item)
    return item


def test_applied_examples_reply_locally_and_withdrawal_removes_them(monkeypatch):
    item = apply("What is my favourite editor?", preferred="You prefer Zed, Boss.")
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *args: None))
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    assert client.post("/api/v1/chat", json={"message": "what is my favourite editor?"}).json()["response"] == "You prefer Zed, Boss."
    assert asyncio.run(voice._reply("what is my favourite editor?", voice.VoiceRequest(speak=False))).response == "You prefer Zed, Boss."
    assert ReviewStore(reviews.path).local_reply("what is my favourite editor?") == "You prefer Zed, Boss."
    reviews.review(item, preferred="You prefer Zed, Boss.")
    assert "Zed" not in asyncio.run(replies.answer("what is my favourite editor?")).content


def test_generic_teachings_and_personal_unknowns_do_not_use_models(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Personal training recall used a provider")
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    monkeypatch.setattr(config, "AI_KNOWLEDGE_ENABLED", True)
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", True)
    apply("What should she remember?", teaching="My sister is Priya.")
    assert "Priya" in asyncio.run(replies.answer("what is my sister's name?")).content
    assert "Priya" not in asyncio.run(replies.answer("what is my brother's name?")).content


def test_captured_personal_question_answer_alias_works():
    apply("What's your favourite food?", teaching="My favourite food is pizza.", kind="question")
    assert "pizza" in asyncio.run(replies.answer("what's my favourite food?")).content


def test_training_memory_list_is_reversible():
    from services.memory.semantic import run_memory_command
    item = apply("Food?", teaching="My favourite food is pizza.")
    assert "pizza" in run_memory_command({"action": "list_memories"})
    reviews.reject(item)
    assert "pizza" not in run_memory_command({"action": "list_memories"})


def test_queue_filters_and_groups_nudges_without_losing_captures():
    reviews.capture("nudge", "Eye break time", {"title": "FRIDAY"})
    latest = reviews.capture("nudge", "Eye break time", {"title": "FRIDAY"})
    question = reviews.capture("question", "Favourite editor?", {})
    assert [r["id"] for r in reviews.queue(kind="question")] == [question]
    grouped = reviews.queue(kind="nudge", grouped=True)
    assert len(grouped) == 1 and grouped[0]["count"] == 2 and grouped[0]["id"] == latest
    assert len(reviews.list("all")) == 3


def test_nudge_feedback_changes_delivery_and_useful_resets_it(monkeypatch):
    sent = []
    monkeypatch.setattr("services.reminders.service.show_toast", lambda *args, **kwargs: sent.append(args) or True)
    assert training.show_toast("FRIDAY", "Eye break time")
    item = reviews.list()[0]["id"]
    reviews.feedback(item, "too_frequent", minutes=60)
    assert training.show_toast("FRIDAY", "Eye break time") is False
    assert len(sent) == 1
    reviews.feedback(item, "useful")
    assert training.show_toast("FRIDAY", "Eye break time")
    assert len(sent) == 2


def test_disabled_nudges_do_not_block_urgent_notices(monkeypatch):
    sent = []
    monkeypatch.setattr("services.reminders.service.show_toast", lambda *args, **kwargs: sent.append(args) or True)
    training.show_toast("FRIDAY", "Battery low")
    reviews.feedback(reviews.list()[0]["id"], "incorrect")
    assert training.show_toast("FRIDAY", "Battery low") is False
    assert training.show_toast("FRIDAY", "Battery low", urgent=True)
    assert len(sent) == 2


def test_only_nudges_accept_structured_feedback():
    item = reviews.capture("question", "What is that?", {})
    with pytest.raises(ValueError):
        reviews.feedback(item, "incorrect")


def test_unanswered_questions_return_after_cooldown_but_answers_do_not():
    question = wonder.SEEDS[0]
    wonder.mark_asked(question, now=1000)
    assert question not in wonder.next_questions(now=1001)
    assert question in wonder.next_questions(n=100, now=1000 + 86400 * 2)
    wonder.mark_answered(question, "Build useful software")
    assert question not in wonder.next_questions(n=100, now=1000 + 86400 * 10)


def test_evening_reserves_personal_questions_and_extended_session_has_more(monkeypatch):
    now = datetime(2026, 10, 14, 22)
    monkeypatch.setattr(evening.brain, "episodes", lambda *args: [])
    monkeypatch.setattr(evening.thoughts, "unsaid_on", lambda *args: [
        SimpleNamespace(kind="unknown", data={"name": f"app{i}"}, id=i) for i in range(3)])
    queue = evening.collect(None, now)
    assert any(item.get("wondered") for item in queue)
    expanded = evening.collect(None, now, extended=True)
    assert len(expanded) > len(queue)
    assert len(expanded) <= 30


def test_live_personal_answers_are_recorded_without_model_extraction():
    question = wonder.SEEDS[2]
    talk._record({"say": question, "wondered": question}, "asked", datetime.now().timestamp())
    assert talk.hear("Pizza") == "answered"
    assert question not in wonder.next_questions(n=100)
    assert wonder.answer_for(question) == "Pizza"


def test_legacy_queue_filters_and_applied_lessons_remain_available():
    reviews.capture("nudge", "Eye break time", {})
    item = reviews.capture("example", "Which editor do I prefer?", {})
    assert [r["id"] for r in reviews.queue(kind="learning")] == [item]
    reviews.review(item, preferred="Zed, Boss.", approve=True)
    reviews.train(item)
    assert reviews.local_reply("Which editor do I prefer?") == "Zed, Boss."
    assert not reviews.get(item)["exportable"]


def test_existing_reviewed_answers_still_reach_personal_replies():
    apply("What do you want to build?", teaching="Build useful software", kind="question")
    apply("What's your favourite food?", teaching="Pizza", kind="question")
    assert len(reviews.learned()) == 2
    assert "Pizza" in asyncio.run(replies.answer("what is my favourite food?")).content
    assert not any(row["exportable"] for row in reviews.learned())


def test_unapproved_legacy_answers_remain_drafts():
    item = reviews.capture("question", wonder.SEEDS[0], {})
    reviews.answer(item, "Build useful software", "answered")
    assert not reviews.learned()
    assert reviews.list()[0]["state"] == "pending"
    assert wonder.answer_for(wonder.SEEDS[0]) is None


def test_ratings_survive_restart_snooze_expires_and_types_are_isolated():
    item = reviews.capture("nudge", "Battery is at 20%. Plug in soon.", {"title": "FRIDAY"}, at=1000)
    reviews.feedback(item, "badly_timed", minutes=10, now=1000)
    restored = ReviewStore(reviews.path)
    assert not restored.allows_nudge("FRIDAY", "Battery is at 18%. Plug in soon.", now=1001)
    assert restored.allows_nudge("FRIDAY", "Battery is at 18%. Plug in soon.", now=1600)
    assert restored.allows_nudge("FRIDAY", "Eye break: look 20 feet away.", now=1001)
    assert restored.allows_nudge("FRIDAY", "Battery is at 8% — plug in now.", now=1001, urgent=True)


def test_feedback_is_applied_before_notification_transport(monkeypatch):
    from services.mind import notifications
    item = reviews.capture("nudge", "Eye break time", {"title": "F.R.I.D.A.Y"})
    reviews.feedback(item, "incorrect")
    async def run():
        return await notifications.notify("Eye break time", transport=lambda *a, **kw: pytest.fail("Disabled nudge delivered"))
    assert not asyncio.run(run())


def test_forget_all_removes_reviewed_memory_and_answer_tracking():
    from services.memory.semantic import run_memory_command
    item = apply("What's your favourite food?", teaching="Pizza", kind="question")
    wonder.mark_answered("What's your favourite food?", "Pizza")
    run_memory_command({"action": "forget_all_memories"})
    assert reviews.get(item)["state"] == "pending"
    assert not reviews.local_reply("what's my favourite food?")
    assert not wonder.answer_for("What's your favourite food?")


def test_generic_tell_me_requests_and_jokes_are_not_personal_memory_queries():
    assert "thoughts" in asyncio.run(replies.answer("tell me a joke")).content
    assert "haven't learned" in asyncio.run(replies.answer("tell me about Zed")).content


def test_answered_personal_questions_are_not_repeated_after_restart():
    question = wonder.SEEDS[2]
    apply(question, teaching="My favourite food is pizza.", kind="question")
    assert question not in wonder.next_questions(n=100)
    assert len(wonder.next_questions(n=100)) == len(set(wonder.next_questions(n=100)))


def test_old_review_database_is_preserved_when_new_tables_are_created(tmp_path):
    import sqlite3
    original = tmp_path / "old.db"
    conn = sqlite3.connect(original)
    conn.execute("""CREATE TABLE reviews (id INTEGER PRIMARY KEY,at REAL,kind TEXT,channel TEXT,question TEXT,
        context TEXT,pattern TEXT,subject TEXT,delivery TEXT,live_answer TEXT,reaction TEXT,answer TEXT,
        teaching TEXT,preferred TEXT,notes TEXT,state TEXT,exportable INTEGER,reviewed_at REAL,trained_at REAL)""")
    conn.execute("""INSERT INTO reviews VALUES(1,1000,'example','manual','Editor?','{}','','','prepared','','','',
                  'I use Zed.','','','trained',0,1000,1000)""")
    conn.commit()
    conn.close()
    restored = ReviewStore(original)
    assert restored.local_reply("Editor?") == "You taught me: I use Zed."
    assert restored.get(1)["teaching"] == "I use Zed."


def test_extended_chat_session_requests_one_brain_decision(monkeypatch):
    from services.automation import intent
    async def forbidden(*a, **kw):
        pytest.fail("Learning interview called a model")
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    async def propose(*args, **kwargs):
        return {'say': 'What would help me understand your current project better?'}
    monkeypatch.setattr('services.mind.inquiry.inquiry.propose', propose)
    result = asyncio.run(intent.try_system_action("start learning session", "openrouter"))
    assert result.success
    assert evening.load()["extended"]
    assert evening.load()["total"] == 1 and evening.load()['queue'] == []


def test_two_review_connections_keep_both_question_answers(tmp_path):
    import concurrent.futures
    path = tmp_path / "questions.db"
    with ReviewStore(path).db():
        pass
    def write(index):
        ReviewStore(path).note_question(f"Question {index}?", answer=f"Answer {index}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, range(10)))
    assert len(ReviewStore(path).question_states()) == 10


def test_manual_examples_do_not_swap_fridays_identity_for_the_owners():
    apply("What is your name?", preferred="I'm FRIDAY.")
    assert reviews.local_reply("What is your name?") == "I'm FRIDAY."
    assert reviews.local_reply("What is my name?") is None


def test_personal_tell_me_queries_stay_local_when_knowledge_is_enabled(monkeypatch):
    monkeypatch.setattr(config, "AI_KNOWLEDGE_ENABLED", True)
    async def forbidden(*a, **kw):
        pytest.fail("Personal query sent to a provider")
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    result = asyncio.run(replies.answer("tell me about my brother"))
    assert "reviewed memory" in result.content


def test_existing_reviewed_personal_answer_still_applies():
    item = reviews.capture("question", "What's your favourite food?", {})
    reviews.answer(item, "Pizza", "answered")
    reviews.review(item, answer="Pizza", teaching="Pizza", approve=True)
    reviews.train(item)
    assert reviews.get(item)["state"] == "trained"
    assert not reviews.get(item)["exportable"]
    assert "Pizza" in reviews.local_reply("what's my favourite food?")


def test_urgent_flag_reaches_delivery_through_notification_dispatch(monkeypatch):
    from services.mind import notifications
    sent = []
    monkeypatch.setattr("services.reminders.service.show_toast", lambda *a, **kw: sent.append(a) or True)
    text = "Battery is at 5% — plug in now or the laptop will shut down soon."
    item = reviews.capture("nudge", text, {"title": "F.R.I.D.A.Y"})
    reviews.feedback(item, "incorrect")
    async def run():
        return await notifications.notify(text, transport=training.show_toast, urgent=True)
    assert asyncio.run(run())
    assert len(sent) == 1
    assert not training.urgent_delivery.get()
