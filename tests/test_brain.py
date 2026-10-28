import asyncio
import random
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services.activity import categories
from services.activity.log import ActivityLog
from services.automation import intent
from services.mind import app_learning, brain, knowledge, life, talk, thoughts, wording

NOW = datetime(2026, 10, 1, 15, 0)


def ask(text):
    return asyncio.run(intent.try_system_action(text, "openai"))


def log_with(tmp_path, rows):
    """An activity log holding (minutes ago it started, minutes long, app, title, project) stretches."""
    log = ActivityLog(str(tmp_path / f"activity{len(list(tmp_path.iterdir()))}.db"))
    for ago, minutes, app, title, project in rows:
        log._insert(at=(NOW - timedelta(minutes=ago)).isoformat(timespec="seconds"), kind="app", app=app, title=title,
                    duration_s=minutes * 60, project=project)
    return log


def front(app, title=None, project=None):
    return SimpleNamespace(app=app, title=title, project=project, app_sequence=lambda: [])


def kinds(now=NOW):
    return [t.kind for t in thoughts.alive(now)]


# ── Senses and knowledge ──────────────────────────────────────────────────────

def test_titles_are_cleaned_into_topics():
    assert knowledge.topic_of("chrome", "(3) Compare Colibri AirLLM - Google Chrome") == "Compare Colibri AirLLM"
    assert knowledge.topic_of("windowsterminal", "◐ Friday capabilities documentation") == "Friday capabilities documentation"
    assert knowledge.topic_of("chrome", "New Tab - Google Chrome") is None   # says nothing
    assert knowledge.topic_of("explorer", "Downloads - File Explorer") is None


def test_every_move_is_filed_with_its_time(tmp_path):
    brain.sense(front("chrome", "Dijkstra's algorithm - Google Chrome"), NOW)
    brain.sense(front("code", "main.py - FRIDAY"), NOW + timedelta(minutes=10))
    chrome, topic = knowledge.get("app:chrome"), knowledge.get("topic:dijkstra's algorithm")
    assert chrome.seconds == topic.seconds == 600 and chrome.times == 1 and chrome.hours[15] == 1
    assert knowledge.get("app:code").seconds == 0  # still going


def test_a_status_mark_in_the_title_is_not_a_move():
    brain.sense(front("windowsterminal", "✳ Build next"), NOW)
    brain.sense(front("windowsterminal", "◐ Build next"), NOW + timedelta(seconds=5))
    assert knowledge.get("app:windowsterminal").times == 1


def test_first_run_goes_through_the_past_without_wondering(tmp_path):
    log = log_with(tmp_path, [(3000, 30, "code", "main.py", None), (60, 20, "chrome", "Hades II wiki - Google Chrome", None)])
    brain.start(log)
    assert knowledge.get("app:code").days == 1 and knowledge.get("topic:hades ii wiki").seconds == 1200
    assert kinds() == []


# ── Wondering ─────────────────────────────────────────────────────────────────

def test_a_program_never_seen_before_makes_her_wonder():
    brain.sense(front("gow", "God of War"), NOW)
    (thought,) = thoughts.alive(NOW)
    assert thought.kind == "new" and thought.data["program"] == "gow" and thought.data["its_window"] == "God of War"
    brain.sense(front("code"), NOW + timedelta(minutes=1))
    brain.sense(front("gow", "God of War"), NOW + timedelta(minutes=2))
    assert kinds(NOW + timedelta(minutes=2)).count("new") == 2  # code was new too; gow isn't wondered about twice


def test_back_after_weeks_and_an_odd_hour():
    with knowledge.db() as conn:
        for day in range(6):  # six afternoons of Spotify, a month ago
            knowledge.see(conn, "app", "spotify", "music", NOW - timedelta(days=40 - day))
    brain.sense(front("spotify"), NOW)
    assert kinds() == ["returned"] and thoughts.alive(NOW)[0].data["days_since_last_time"] >= 14
    night = NOW.replace(hour=3) + timedelta(days=1)
    brain.sense(front("code"), night - timedelta(minutes=1))
    brain.sense(front("spotify"), night)
    odd = [t for t in thoughts.alive(night) if t.kind == "odd_hour"]
    assert odd and odd[0].data["time_now"] == "3 AM" and "3 PM" in odd[0].data["usual_times"]


def test_restless_switching():
    for i in range(brain.RESTLESS_SWITCHES + 1):
        brain.sense(front("chrome" if i % 2 else "code"), NOW + timedelta(seconds=10 * i))
    assert "restless" in kinds(NOW + timedelta(minutes=3))


def test_thoughts_fade_and_only_strong_ones_are_worth_saying():
    thoughts.add("new", "app:gow", {"program": "gow"}, 0.9, NOW)
    assert thoughts.top(NOW).kind == "new"
    assert thoughts.top(NOW + timedelta(minutes=45)).now_strength(NOW + timedelta(minutes=45)) == 0.45
    assert thoughts.top(NOW + timedelta(hours=2)) is None  # she's moved on


# ── Past, present, what's next ────────────────────────────────────────────────

DAY = [(200, 40, "code", "assignment.py - dbms", None),          # 11:40–12:20 coding
       (160, 0.5, "whatsapp", "WhatsApp", None),          # a glance
       (159, 20, "code", "assignment.py - dbms", None),          # … still coding → 12:41
       (90, 30, "chrome", "Lofi mix - YouTube - Google Chrome", None),  # 13:30–14:00
       (10, 9, "chrome", "Lofi mix - YouTube - Google Chrome", None)]   # 14:50–now


WORK_THEN_GAME = [(40, 30, "code", "main.py", None), (10, 9, "valorant", "VALORANT", None)]


def test_the_day_is_cut_into_episodes_and_glances_are_folded_in(tmp_path):
    found = brain.episodes(log_with(tmp_path, DAY), NOW)
    assert [(e.thread, round(e.seconds / 60)) for e in found] == [("coding", 60), ("entertainment", 30), ("entertainment", 9)]
    assert found[0].label() == "coding (assignment.py - dbms)"
    assert brain.present(found, NOW).thread == "entertainment"
    assert brain.dropped(found, NOW).thread == "coding"


def test_the_timeline_tells_past_present_and_what_was_left(tmp_path):
    text = brain.timeline(log_with(tmp_path, DAY), NOW)
    assert text.startswith("Right now: I don't have a fresh activity observation")
    assert "Recorded earlier" in text and "Earlier focus: coding (assignment.py - dbms)" in text
    assert "completion is unknown" in text


def test_something_left_hanging_and_a_jump_out_of_work_make_her_wonder(tmp_path):
    log = log_with(tmp_path, DAY)
    brain.think(log, NOW)
    assert "dropped" in kinds()
    brain.think(log_with(tmp_path, WORK_THEN_GAME), NOW)
    (thought,) = [t for t in thoughts.alive(NOW) if t.kind == "jump"]
    assert thought.data["was"].startswith("coding") and thought.data["my_guess"] == brain.GUESSES["gaming"]


def test_the_boss_answer_becomes_the_reason_next_time(tmp_path):
    brain.think(log_with(tmp_path, WORK_THEN_GAME), NOW)
    thought = thoughts.top(NOW)
    brain.answered(thought.id, "my brain needed a break", NOW)
    assert thoughts.reason_for("jump:coding>gaming") == "my brain needed a break"
    later = NOW + timedelta(days=2)
    log = ActivityLog(str(tmp_path / "later.db"))
    for ago, minutes, app in ((40, 30, "code"), (10, 9, "valorant")):
        log._insert(at=(later - timedelta(minutes=ago)).isoformat(timespec="seconds"), kind="app", app=app,
                    title=None, duration_s=minutes * 60, project=None)
    brain.think(log, later)
    assert thoughts.top(later).data["last_time_the_boss_said"] == "my brain needed a break"


def test_a_missing_regular_is_noticed_once_the_boss_has_settled(tmp_path):
    with knowledge.db() as conn:
        for day in range(1, 7):
            for hour in (13, 14):
                knowledge.see(conn, "app", "spotify", "music", NOW.replace(hour=hour) - timedelta(days=day))
                knowledge.see(conn, "app", "code", "coding", NOW.replace(hour=hour) - timedelta(days=day))
        knowledge.see(conn, "app", "code", "coding", NOW)
    brain.think(log_with(tmp_path, [(50, 49, "code", "main.py", None)]), NOW)
    (thought,) = [t for t in thoughts.alive(NOW) if t.kind == "skipped"]
    assert thought.data["program"] == "spotify" and thought.data["usually_open_by"] == "3 PM"


# ── Curiosity ─────────────────────────────────────────────────────────────────

def lookup_says(monkeypatch, reply, seen=None):
    async def complete(provider, messages, system, max_tokens, **kw):
        if seen is not None:
            seen.append(messages[0].content)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(content=reply, provider=provider)
    monkeypatch.setattr("providers.failover.complete_with_failover", complete)


def unplaced_app(minutes=5):
    with knowledge.db() as conn:
        knowledge.see(conn, "app", "gow", "other", NOW - timedelta(hours=1), "God of War")
        knowledge.spend(conn, "app", "gow", minutes * 60)


def test_she_looks_up_what_she_cant_place_with_only_its_name(tmp_path, monkeypatch):
    unplaced_app()
    asked = []
    lookup_says(monkeypatch, '{"known": true, "what": "God of War, an action-adventure game.", "category": "gaming"}', asked)
    log = log_with(tmp_path, [])
    asyncio.run(brain.learn_something(log, NOW))
    assert asked == ['What is "gow"? It is the name of a Windows program.']
    thing = knowledge.get("app:gow")
    assert thing.about is None and thing.category == "other" and thing.source == "rule"
    proposal = app_learning.pending(thing.key)[0]
    assert proposal["description"].startswith("God of War")
    assert categories.app_category("gow") == "other"
    assert kinds() == [] and knowledge.due_lookup(NOW) is None
    assert app_learning.resolve(app_learning.identity(proposal), "yes", NOW) == "confirmed"
    assert categories.app_category("gow") == "gaming"


def test_what_the_model_doesnt_know_she_asks_the_boss_and_the_answer_teaches_her(tmp_path, monkeypatch):
    unplaced_app()
    lookup_says(monkeypatch, '{"known": false, "what": "", "category": "other"}')
    asyncio.run(brain.learn_something(log_with(tmp_path, []), NOW))
    proposal = app_learning.pending("app:gow")[0]
    assert proposal["description"] == "" and proposal["name"] == "gow"
    app_learning.resolve(app_learning.identity(proposal), "it's a game, God of War", NOW)
    thing = knowledge.get("app:gow")
    assert thing.source == "boss" and thing.category == "gaming" and categories.app_category("gow") == "gaming"


def test_with_no_model_she_leaves_an_owner_clarification(tmp_path, monkeypatch):
    unplaced_app()
    lookup_says(monkeypatch, RuntimeError("offline"))
    asyncio.run(brain.learn_something(log_with(tmp_path, []), NOW))
    assert kinds() == [] and knowledge.due_lookup(NOW) is None
    assert app_learning.pending("app:gow")[0]["description"] == ""


def test_the_small_local_model_isnt_trusted_with_facts(tmp_path, monkeypatch):
    unplaced_app()
    asked = []

    async def only_ollama(provider, messages, system, max_tokens, **kw):
        asked.append(1)
        return SimpleNamespace(content='{"known": true, "what": "A golf game.", "category": "gaming"}', provider="ollama")
    monkeypatch.setattr("providers.failover.complete_with_failover", only_ollama)
    log = log_with(tmp_path, [])
    asyncio.run(brain.learn_something(log, NOW))
    assert knowledge.get("app:gow").about is None and kinds() == []
    assert app_learning.pending("app:gow")[0]["description"] == ""
    asyncio.run(brain.learn_something(log, NOW + timedelta(minutes=1)))
    assert len(asked) == 1  # and she doesn't keep trying every minute
    asyncio.run(brain.learn_something(log, NOW + brain.LOOKUP_RETRY))
    assert len(asked) == 1  # owner clarification stays pending; no repeated background lookup


def test_a_short_interlude_doesnt_split_an_episode(tmp_path):
    log = log_with(tmp_path, [(60, 20, "code", "main.py", None), (40, 5, "whatsapp", "WhatsApp", None),
                              (35, 20, "code", "main.py", None)])
    assert [(e.thread, round(e.seconds / 60)) for e in brain.episodes(log, NOW)] == [("coding", 40)]


def test_a_passing_glance_isnt_looked_up():
    unplaced_app(minutes=0.5)
    assert knowledge.due_lookup(NOW) is None


# ── Wording: the model's only job ─────────────────────────────────────────────

RAW = {"kind": "new", "noticed": "a program I have never seen the Boss use before", "program": "gow",
       "its_window": "God of War", "pattern": "new:gow"}


def test_the_model_gets_only_the_raw_data_of_that_one_thought(monkeypatch):
    seen = []
    lookup_says(monkeypatch, "God of War, Boss? Bold choice for a Thursday.", seen)
    assert asyncio.run(wording.say(RAW)) == "God of War, Boss? Bold choice for a Thursday."
    assert seen == ["noticed: a program I have never seen the Boss use before\nprogram: gow\nits window: God of War"]


def test_a_line_that_loses_the_name_or_comes_from_the_small_local_model_is_said_plainly(monkeypatch):
    lookup_says(monkeypatch, "Gwent seems less mysterious now.")  # made up: gow is gone
    assert asyncio.run(wording.say(RAW)) == wording.plain(RAW)

    async def only_ollama(provider, messages, system, max_tokens, **kw):
        return SimpleNamespace(content="gow, Boss? Bold.", provider="ollama")
    monkeypatch.setattr("providers.failover.complete_with_failover", only_ollama)
    assert asyncio.run(wording.say(RAW)) == wording.plain(RAW)


def test_with_no_model_she_says_it_plainly(monkeypatch):
    lookup_says(monkeypatch, RuntimeError("offline"))
    assert asyncio.run(wording.say(RAW)) == "That's new, Boss: gow (God of War). What is it?"
    lookup_says(monkeypatch, "")  # a useless reply counts as no model
    assert asyncio.run(wording.say({"kind": "question", "ask": "What's your favourite food?"})) == "What's your favourite food?"


def test_every_kind_of_thought_can_be_said_without_a_model(tmp_path):
    for kind, data in {
        "returned": {"program": "spotify", "days_since_last_time": 20},
        "odd_hour": {"program": "code", "time_now": "3 AM", "usual_times": ["2 PM", "3 PM"]},
        "jump": {"was": "coding", "for_minutes": 40, "now": "gaming", "my_guess": "taking a break"},
        "restless": {"window_switches": 14, "in_minutes": 5},
        "dropped": {"left": "coding", "left_at": "4:10 PM"},
        "skipped": {"program": "spotify", "usually_open_by": "3 PM"},
        "learned": {"name": "gow", "it_is": "God of War, a game."},
        "unknown": {"name": "gow"},
        "start": {}, "back": {}, "checkin": {"the_boss_is": "coding", "for_minutes": 30},
        "followup": {"this_just_happened": "DBMS exam on Friday"}, "plan": {"earlier_the_boss_said": "upgrading friday"},
        "feeling": life.feeling(NOW),
    }.items():
        assert wording.plain({"kind": kind, **data}).strip()


# ── Her mind drives what she says ─────────────────────────────────────────────

class Log:
    app = "code"

    def app_seconds(self, name, since, now=None):
        return 600


def test_a_cognitively_selected_thought_retains_its_answer_feedback(monkeypatch):
    lookup_says(monkeypatch, RuntimeError("offline"))
    brain.sense(front("gow", "God of War"), NOW)
    where, weight = talk.situation(Log(), {}, NOW, came_back=False)
    assert where == "notice_new" and weight > 1
    async def choose(now=None, **kwargs):
        return {'say': 'What is gow used for?', 'thought': thoughts.top(NOW).id}
    monkeypatch.setattr('services.mind.inquiry.inquiry.propose', choose)
    line = asyncio.run(talk.compose(Log(), where, {}, NOW))
    assert line['say'] == 'What is gow used for?'
    talk._record(line, where, NOW.timestamp())
    assert thoughts.top(NOW) is None                       # said: off her mind
    pending = talk.load()["pending"]
    talk.hear("a game, god of war", now=pending["at"] + 5)
    assert knowledge.get("app:gow").about == "a game, god of war" and knowledge.get("app:gow").category == "gaming"


@pytest.mark.parametrize("kind", ["new", "unknown"])
def test_an_explanation_is_kept_even_when_the_category_is_known(kind):
    with knowledge.db() as conn:
        knowledge.see(conn, "app", "gow", "gaming", NOW, "God of War")
    thoughts.add(kind, "app:gow", {"name": "gow"}, 0.9, NOW)
    thought = thoughts.top(NOW)
    assert knowledge.get("app:gow").placed

    # An explanation without a category keyword should preserve the existing category.
    brain.answered(thought.id, "God of War, my favourite", NOW)
    thing = knowledge.get("app:gow")
    assert thing.about == "God of War, my favourite"
    assert thing.category == "gaming" and thing.source == "boss"


def test_without_a_thought_she_asks_from_her_list_or_checks_in(monkeypatch):
    always_ask = random.Random(0)
    always_ask.random = lambda: 0.0
    assert talk.choose(Log(), "chill", {}, NOW, always_ask)["raw"]["kind"] == "question"
    never_ask = random.Random(0)
    never_ask.random = lambda: 1.0
    raw = talk.choose(Log(), "study", {}, NOW, never_ask)["raw"]
    assert raw["kind"] == "checkin" and raw["the_boss_is"] == "code"
    assert talk.choose(Log(), "start", {}, NOW)["raw"]["kind"] == "start"


# ── Her own life ──────────────────────────────────────────────────────────────

def test_positive_engagement_fades_and_quiet_is_respected():
    at = NOW.timestamp()
    assert life.mood(NOW)[0] == "content"
    life.feel("shushed", at)
    assert life.mood(NOW)[0] == "content"
    assert life.mood(NOW + timedelta(hours=6))[0] == "content"
    life.feel("answered", at), life.feel("answered", at), life.feel("answered", at)
    assert life.mood(NOW)[0] == "pleased"
    assert life.mood(NOW, away_minutes=90)[0] == "quiet"


def test_her_day_goes_into_her_diary():
    brain.sense(front("gow", "God of War"), NOW)
    life.feel("answered", NOW.timestamp())
    line = life.close_day(NOW)
    assert line.startswith("I noticed 1 thing") and "got 1 answer" in line
    assert '"day": "2026-10-01"' in life.diary_path.read_text(encoding="utf-8")


# ── Commands ──────────────────────────────────────────────────────────────────

def test_commands(monkeypatch):
    monkeypatch.setattr('services.mind.cognition_context.live_state',
                        lambda: {'activity': 'coding', 'away': False, 'idle_band': 'present', 'mode_name': 'normal'})
    lookup_says(monkeypatch, RuntimeError("offline"))
    assert ask("what am i doing").message.startswith("Right now:")
    assert ask("where did i leave off").message.startswith("Right now:")
    assert ask("how are you feeling").message.startswith("Feeling content, Boss")
    with knowledge.db() as conn:
        knowledge.see(conn, "app", "electron", "other", NOW, "Catjang")
    knowledge.teach("app:electron", "a desktop cat pet")
    assert "a desktop cat pet (you told me)" in ask("what do you know about catjang").message
    assert brain.match_brain_command("what do you know about ravi") is None  # people stay with her memory
    assert "Mood:" in ask("what's on your mind").message
