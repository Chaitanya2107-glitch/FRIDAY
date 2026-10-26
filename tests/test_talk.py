import asyncio
import time
import random
import pytest
from datetime import datetime, timedelta

from interfaces.api.routes import mind as mind_route
from services.automation import intent
from services.mind import talk

NOW = datetime(2026, 9, 30, 15, 0)
ACTIVE = 10  # idle seconds: at the laptop, not mid-typing


class Log:
    app = "windowsterminal"

    def app_totals(self, start, end):
        return {"windowsterminal": 3600, "electron": 1200}

    def app_seconds(self, name, since, now=None):
        return 600


class Always(random.Random):  # the dice always say "talk"
    def random(self):
        return 0.0

    def betavariate(self, a, b):
        return 1.0


class First(Always):  # …and she always picks the first thing on her list
    def choice(self, seq):
        return seq[0]


def ask(text):
    return asyncio.run(intent.try_system_action(text, "openai"))


def said(monkeypatch, line="What are you building, Boss?", **kw):
    async def compose(log, where, state, now):
        return {"say": line, "about": ""}
    monkeypatch.setattr(talk, "compose", compose)
    args = dict(busy=False, idle=ACTIVE, rng=Always())
    args.update(kw)
    return asyncio.run(talk.tick(Log(), args.pop("now", NOW), args["busy"], args["idle"], args["rng"]))


def test_switched_by_voice():
    assert ask("you can talk freely").success and talk.is_on()
    assert ask("be quiet for 30 minutes").success and talk.load()["paused_until"] > 0
    assert ask("stop talking on your own").success and not talk.is_on()


@pytest.mark.parametrize('message', ['stop asking questions', 'not now'])
def test_question_stop_controls_are_local_and_clear_pending(message, monkeypatch):
    from core.config import config
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(config, 'AI_LANGUAGE_ENABLED', False)
    talk._record({'say': 'What is blocking this task?'}, 'asked', time.time())
    assert ask(message).success
    assert not talk.load().get('pending')
    assert not talk.is_on() or talk.load()['paused_until'] > time.time()


def test_pausing_blocks_already_queued_question_delivery(monkeypatch):
    sent = []
    monkeypatch.setattr('services.reminders.service.show_toast', lambda *a, **kw: sent.append(a))
    talk.pause(60)
    asyncio.run(talk.deliver('What is blocking this task?'))
    assert not sent


def test_on_by_default_and_hard_limits(monkeypatch):
    assert talk.is_on()
    talk.set_on(False)
    assert said(monkeypatch) is None                   # switched off
    talk.set_on(True)
    assert said(monkeypatch, busy=True) is None        # fullscreen / gaming / quiet mode
    assert said(monkeypatch, idle=1) is None           # mid-typing
    assert said(monkeypatch, idle=600) is None         # away from the laptop
    monkeypatch.setattr(talk, "mic_in_use", lambda: True)
    assert said(monkeypatch) is None                   # on a call
    monkeypatch.setattr(talk, "mic_in_use", lambda: False)
    assert said(monkeypatch) == "What are you building, Boss?"
    assert said(monkeypatch) is None                   # waiting for the answer / too soon


def test_answers_teach_when_talking_is_welcome(monkeypatch):
    talk.set_on(True)
    said(monkeypatch)
    where = talk.load()["pending"]["where"]
    before = talk.welcome(where)
    assert talk.hear("working on the catjang login page, it's going okay") == "answered"
    assert talk.welcome(where) > before
    assert talk.hear("anything") is None               # nothing pending any more


def test_a_brush_off_teaches_and_pauses(monkeypatch):
    talk.set_on(True)
    said(monkeypatch)
    where = talk.load()["pending"]["where"]
    before = talk.welcome(where)
    assert talk.hear("not now friday") == "shushed"
    assert talk.welcome(where) < before and talk.load()["paused_until"] > 0


def test_a_long_answer_saying_later_is_still_an_answer(monkeypatch):
    talk.set_on(True)
    said(monkeypatch)
    assert talk.hear("I'll finish the DBMS assignment later tonight after dinner") == "answered"


def test_no_answer_counts_a_little_against(monkeypatch):
    talk.set_on(True)
    said(monkeypatch)
    where = talk.load()["pending"]["where"]
    before = talk.welcome(where)
    state = talk.load()
    talk._expire(state, state["pending"]["at"] + talk.ANSWER_SECONDS + 1)
    assert "pending" not in talk.load() and talk.welcome(where) < before


def test_coming_back_is_an_opening(monkeypatch):
    state = {}
    talk._was_away = True
    asyncio.run(talk.tick(Log(), NOW, False, ACTIVE, random.Random(0)))  # off: nothing said, but noticed
    assert talk.situation(Log(), state, NOW, NOW.timestamp() < talk._back_until) == ("back", talk.OPENING)


def test_delivery_speaks_saves_and_hands_the_question_to_the_tray(monkeypatch):
    spoken, toasts = [], []
    monkeypatch.setattr("interfaces.api.routes.voice._speak_in_background", spoken.append)
    monkeypatch.setattr("services.reminders.service.show_toast", lambda title, text, *a, **kw: toasts.append(text))

    async def go():
        await talk.deliver("How's the assignment going?")
        return await mind_route.next_ask(wait=1), await mind_route.next_ask(wait=0)
    first, second = asyncio.run(go())
    assert spoken == toasts == ["How's the assignment going?"]
    assert first == {"question": "How's the assignment going?"} and second == {"question": None}


def test_right_after_launch_she_asks_what_youre_up_to_and_follows_up(monkeypatch):
    talk._launch_pending = True
    raws = []

    async def compose(log, where, state, now):
        raws.append(talk.choose(log, where, state, now, First())["raw"])
        return {"say": "Morning, Boss. What are we up to today?" if where == "start" else "How's it going?", "about": ""}
    monkeypatch.setattr(talk, "compose", compose)
    never = random.Random(0)
    never.random = lambda: 1.0  # the dice would never say "talk" — the launch question doesn't need them
    assert asyncio.run(talk.tick(Log(), NOW, False, ACTIVE, never)) == "Morning, Boss. What are we up to today?"
    assert raws[0]["kind"] == "start" and "just come online" in raws[0]["moment"] and not talk._launch_pending
    talk.hear("finishing the DBMS assignment then some catjang")
    assert talk.load()["plan"]["text"].startswith("finishing the DBMS")
    later = NOW + timedelta(minutes=talk.MIN_GAP_MINUTES + 1)
    asyncio.run(talk.tick(Log(), later, False, ACTIVE, Always()))
    assert raws[-1]["kind"] == "plan" and "finishing the DBMS assignment" in raws[-1]["earlier_the_boss_said"]  # she checks in on it


def test_the_launch_question_can_be_unlearned(monkeypatch):
    talk._launch_pending = True
    talk._save({"beliefs": {"start": [0.5, 9.0]}})  # "not now" at launch, many times
    assert said(monkeypatch) is None and not talk._launch_pending


def test_late_night_is_learned_not_blocked(monkeypatch):
    talk.set_on(True)
    night = datetime(2026, 9, 30, 2, 30)
    assert talk.situation(Log(), {}, night, False)[0] == "late"
    assert said(monkeypatch, now=night) == "What are you building, Boss?"  # quiet hours don't silence her
    talk.hear("not now, it's 2am")
    assert talk.welcome("late") < 0.5  # …but she learns


def test_whats_on_your_mind_mentions_talking():
    talk.set_on(True)
    assert "Talking on my own" in ask("what's on your mind").message or "Free will is on" in ask("what's on your mind").message


# ── What she wants to know ────────────────────────────────────────────────────

from services.mind import wonder  # noqa: E402


def test_her_list_starts_with_get_to_know_you_questions_and_crosses_them_off():
    first = wonder.next_questions()
    assert len(first) == 3 and first[0] == wonder.SEEDS[0]
    wonder.mark_asked(first[0])
    assert first[0] not in wonder.next_questions()


def test_reflection_questions_come_first_and_are_not_repeated():
    assert wonder.add(["Why do you open WhatsApp right after class?", "What's your favourite food?"]) == 2
    assert wonder.next_questions()[0] == "Why do you open WhatsApp right after class?"
    wonder.mark_asked("Why do you open WhatsApp right after class?")
    assert wonder.add(["why do you open whatsapp right after class"]) == 0  # already asked


def test_questions_fit_relaxed_moments_not_study():
    raw = talk.choose(Log(), "chill", {}, NOW, First())["raw"]
    assert (raw["kind"], raw["ask"]) == ("question", wonder.SEEDS[0])
    assert talk.choose(Log(), "study", {}, NOW, First())["raw"]["kind"] == "checkin"


def test_a_used_question_is_crossed_off(monkeypatch):
    talk.set_on(True)
    q = wonder.next_questions()[0]

    async def compose(log, where, state, now):
        return {"say": "Random one, Boss — what do you want to do after college?", "about": "", "wondered": q}
    monkeypatch.setattr(talk, "compose", compose)
    asyncio.run(talk.tick(Log(), NOW, False, ACTIVE, Always()))
    assert q not in wonder.next_questions()
    assert talk.load()["pending"]["question"].startswith("Random one")


def test_ask_me_something(monkeypatch):
    async def compose(log, where, state, now):
        assert where == "asked"
        return {"say": "What's your favourite food?", "about": "", "wondered": "What's your favourite food?"}
    monkeypatch.setattr(talk, "compose", compose)
    reply = ask("ask me something")
    assert reply.message == "What's your favourite food?" and talk.load()["pending"]["where"] == "asked"


def test_an_answer_is_learned_with_its_question(monkeypatch):
    from services.memory.semantic import semantic_memory
    learned = []
    monkeypatch.setattr(semantic_memory, "learn_in_background", lambda msg, provider, question=None: learned.append((question, msg)))
    talk.set_on(True)
    said(monkeypatch, line="What's your favourite food?")
    talk.hear("pizza, always pizza")
    assert learned == [("What's your favourite food?", "pizza, always pizza")]


def test_memory_learns_a_short_answer_when_it_has_the_question(monkeypatch):
    from services.memory.semantic import semantic_memory
    seen = []

    async def learn(message, provider):
        seen.append(message)
    monkeypatch.setattr("core.config.config.SEMANTIC_MEMORY_LEARN", True)
    monkeypatch.setattr(semantic_memory, "_learn", learn)

    async def go():
        semantic_memory.learn_in_background("pizza", "openai")                              # no "I/my": skipped
        semantic_memory.learn_in_background("pizza", "openai", question="Favourite food?")  # with the question: learned
        await asyncio.sleep(0)
    asyncio.run(go())
    assert seen == ['Friday asked the user: "Favourite food?"\nThe user answered: "pizza"']


def test_a_reply_wrapped_in_json_by_a_small_model_is_still_said():
    from services.mind import wording
    assert wording._line('Evening, Boss. What are you up to?') == "Evening, Boss. What are you up to?"
    assert wording._line('Hi. {"say": "Hi, Boss!", "about": ""}') == "Hi, Boss!"
    assert wording._line('{"say": broken') is None
    assert wording._line("") is None


def test_she_follows_up_on_plans(monkeypatch):
    monkeypatch.setattr(talk, "_memory_plans", lambda: (["User had a DBMS exam on Friday 3 Oct"], ["User has a trip on Sunday"]))
    line = talk.choose(Log(), "followup", {}, NOW)
    assert line["raw"]["this_just_happened"] == line["followed_up"] == "User had a DBMS exam on Friday 3 Oct"
    assert talk.situation(Log(), {}, NOW, came_back=False) == ("followup", talk.OPENING)  # a moment to speak


def test_a_follow_up_is_asked_once(monkeypatch):
    from services.memory.semantic import semantic_memory
    marked = []
    monkeypatch.setattr(semantic_memory, "mark_followed_up", marked.append)
    talk._record({"say": "How did the DBMS exam go?", "about": "", "followed_up": "User had a DBMS exam"}, "followup", NOW.timestamp())
    assert marked == ["User had a DBMS exam"]
