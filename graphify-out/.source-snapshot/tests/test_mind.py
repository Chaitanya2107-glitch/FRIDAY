import asyncio
import random
from datetime import datetime, timedelta

from services.automation import intent
from services.automation.system_control import AutomationError
from services.mind import corrections, humour, learner, reflection


def ask(text):
    return asyncio.run(intent.try_system_action(text, "openai"))


# ── Humour ────────────────────────────────────────────────────────────────────

def test_reactions_teach_when_jokes_land():
    start = humour.welcome("study")
    humour.told("study", "study_mode", now=1000)
    assert humour.hear("lol good one", now=1010) == "liked"
    liked = humour.welcome("study")
    humour.told("study", "study_mode", now=2000)
    assert humour.hear("not now friday, I'm serious", now=2010) == "disliked"
    assert liked > start > humour.welcome("gaming") - 1  # a laugh raised it
    assert humour.welcome("study") < liked               # a complaint lowered it


def test_a_late_reply_teaches_nothing():
    humour.told("late", "late", now=0)
    assert humour.hear("haha", now=humour.REACTION_MINUTES * 60 + 1) is None
    assert "late" not in humour.load().get("beliefs", {})


def test_fading_pulls_back_towards_the_prior():
    for i in range(10):
        humour.told("coding", "everyday", now=i * 100)
        humour.hear("lmao", now=i * 100 + 1)
    before = humour.welcome("coding")
    humour.fade()
    assert humour.PRIOR[0] / sum(humour.PRIOR) < humour.welcome("coding") < before


def test_learned_dislike_means_fewer_jokes():
    for i in range(15):
        humour.told("deadline", "deadline", now=i * 100)
        humour.hear("stop joking", now=i * 100 + 1)
    rng = random.Random(1)
    assert sum(humour.should_joke("deadline", rng=rng) for _ in range(200)) < 30
    assert "keep it minimal" in humour.dial("deadline")


# ── Corrections ───────────────────────────────────────────────────────────────

def _apps(monkeypatch):
    def open_app(name):
        if name != "spotify":
            raise AutomationError(f"I couldn't find an app called '{name}' on this PC.")
        return "Opening Spotify."
    monkeypatch.setattr(intent.system, "open_app", open_app)


def test_i_meant_teaches_the_missed_message(monkeypatch):
    _apps(monkeypatch)
    assert not getattr(ask("open the thingy"), "success", False)  # chat or a failure: a miss
    fixed = ask("no, I meant open spotify")
    assert fixed.success and "next time" in fixed.message
    assert ask("open the thingy").message.startswith("Opening Spotify")  # learned
    assert corrections.recent() == [("open the thingy", "open spotify")]


def test_a_bare_no_after_a_success_is_a_change_of_mind(monkeypatch):
    _apps(monkeypatch)
    assert ask("open spotify").success
    assert corrections.correction("no, open chrome") is None
    assert corrections.correction("I meant open chrome") == ("open spotify", "open chrome")


def test_an_old_message_is_not_corrected():
    corrections.note("open the thingy", False, now=0)
    assert corrections.correction("I meant open spotify", now=corrections.WINDOW_SECONDS + 1) is None


def test_typing_is_never_learned():
    assert not corrections.learn("say hi", "type hi", [{"type": "system", "action": "type_text", "text": "hi"}])
    assert corrections.lookup("say hi") is None


# ── Self-training predictor ───────────────────────────────────────────────────

class FakeLog:
    def __init__(self, rows):
        self.rows = rows

    def app_sequence(self):
        return self.rows


def _days(pattern, days=14, start=datetime(2026, 9, 1, 9, 0)):
    rows, at = [], start
    for d in range(days):
        at = start + timedelta(days=d)
        for _ in range(8):
            for app in pattern:
                rows.append((at.isoformat(), app))
                at += timedelta(minutes=3)
    return rows


def test_train_scores_and_records_who_is_in_charge():
    log = FakeLog(_days(["code", "chrome", "spotify", "code", "terminal"]))
    result = learner.train(log, now=datetime(2026, 9, 15))
    assert result and result["in_charge"] in ("model", "counting")
    assert (result["in_charge"] == "model") == learner.model_path.exists()
    assert "tested" in learner.summary()
    if result["in_charge"] == "model":
        assert learner.top("code", "terminal", datetime(2026, 9, 11, 10)) == ["chrome", "spotify", "terminal"][:3]


def test_too_little_data_trains_nothing():
    assert learner.train(FakeLog(_days(["a", "b"], days=1)), now=datetime(2026, 9, 2)) is None
    assert learner.top("a", None, datetime.now()) is None


# ── Reflection + "what's on your mind" ────────────────────────────────────────

def test_profile_goes_into_the_prompt():
    assert reflection.prompt_section() == ""
    reflection._save({"lines": ["The Boss studies late."], "humour": "Dry jokes land."})
    section = reflection.prompt_section()
    assert "The Boss studies late." in section and "Dry jokes land." in section


def test_whats_on_your_mind():
    reflection._save({"lines": ["The Boss codes in Windows Terminal."]})
    reply = ask("what's on your mind?")
    assert reply.success and "Windows Terminal" in reply.message and "predictor" in reply.message


def test_reflection_reply_is_parsed_loosely():
    assert reflection._parse('Sure! {"profile": ["a"], "facts": []} done')["profile"] == ["a"]
    assert reflection._parse("no json here") is None


def test_she_rethinks_every_few_hours_when_theres_something_new(monkeypatch):
    said, runs = ["hi"], []

    async def fake_reflect(log, day):
        runs.append(day)
        reflection._save({**reflection.load(), "updated": day.isoformat(), "messages_seen": len(said)})
        return "ok"
    monkeypatch.setattr(reflection, "messages_on", lambda day: list(said))
    monkeypatch.setattr(reflection, "reflect", fake_reflect)
    now = datetime(2026, 9, 30, 12, 0)
    assert asyncio.run(reflection.reflect_if_due(None, now)) == "ok"
    assert asyncio.run(reflection.reflect_if_due(None, now + timedelta(hours=1))) is None   # too soon
    assert asyncio.run(reflection.reflect_if_due(None, now + timedelta(hours=4))) is None   # nothing new said
    said.append("I'm starting the ML assignment")
    assert asyncio.run(reflection.reflect_if_due(None, now + timedelta(hours=4))) == "ok"
    assert len(runs) == 2
