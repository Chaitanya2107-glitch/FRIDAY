import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services.activity import habits
from services.activity.habit_patterns import Habit
from services.automation import intent
from services.mind import brain, foresight, learner, thoughts, wording

NOW = datetime(2026, 10, 1, 15, 0)  # a Thursday


def ask(text):
    return asyncio.run(intent.try_system_action(text, "openai"))


def log_of(history, app=None):
    """A log whose past is `history` (apps in order, a minute apart, days ago) and whose front app is `app`."""
    start = NOW - timedelta(days=3)
    rows = [((start + timedelta(minutes=i)).isoformat(), name) for i, name in enumerate(history)]
    commands = []
    return SimpleNamespace(app=app, app_sequence=lambda: rows, log_command=lambda parsed, ok: commands.append(parsed),
                           commands=commands, db_path="test", habit_rows=lambda since: [])


# 8 of 10 times: spotify after code (plain there-and-back switching is learned as "back", not as a pattern)
CODE_THEN_SPOTIFY = ["chrome", "code", "spotify"] * 8 + ["chrome", "code", "whatsapp"] * 2


def settle(log, app="code", model=None, monkeypatch=None):
    """The Boss switches to `app` and stays a minute."""
    if monkeypatch:
        monkeypatch.setattr(learner, "guess", lambda a, before, when: model)
        learner.shadow_path.parent.mkdir(parents=True, exist_ok=True)
        learner.shadow_path.write_bytes(b"trained")  # a trained model exists
    foresight._pending = foresight._counts = None  # a fresh arrival, with this log's past
    log.app = app
    foresight.moved(log, app, NOW)
    return NOW + timedelta(seconds=foresight.SETTLE_SECONDS)


# ── Next app: her counting against the model ──────────────────────────────────

def test_she_predicts_from_her_own_counts_and_asks_the_boss():
    log = log_of(CODE_THEN_SPOTIFY)
    ((kind, subject, data, _),) = foresight.think(log, settle(log))
    assert (kind, subject) == ("prediction", "next:code>spotify")
    assert data["program"] == "spotify" and data["after"] == "VS Code" and data["my_trained_model"] == "not trained yet"
    assert data["because"] == "8 of the 10 times the Boss left VS Code, they went there"
    assert wording.plain({"kind": kind, **data}).startswith("My guess, Boss: after VS Code you'll open spotify (8 of")
    assert "context" not in wording._facts(data)  # her bookkeeping isn't for the model


def test_no_prediction_before_the_boss_settles_or_without_enough_behind_it():
    log = log_of(CODE_THEN_SPOTIFY)
    settle(log)
    assert foresight.think(log, NOW + timedelta(seconds=5)) == []
    thin = log_of(["chrome", "code", "spotify"] * 2)
    assert foresight.think(thin, settle(thin)) == []


def test_alt_tabbing_back_is_not_a_prediction():
    log = log_of(["code", "spotify"] * 10)  # always straight back
    foresight.moved(log, "spotify", NOW - timedelta(minutes=1))
    log.app = "code"
    foresight.moved(log, "code", NOW)
    assert foresight._pending["own"] == "spotify"  # she does expect it …
    assert foresight.think(log, NOW + timedelta(minutes=1)) == []  # … but it isn't worth asking about


def test_the_first_prediction_of_the_day_needs_less_behind_it():
    history = (["chrome", "code", "spotify"] * 4 + ["chrome", "code", "whatsapp"] * 3
               + ["chrome", "code", "notepad"] * 3)  # spotify: 4 of 10
    log = log_of(history)
    later = settle(log)
    assert [t[0] for t in foresight.think(log, later)] == ["prediction"]
    thoughts.add("prediction", "next:other>thing", {}, 0.5, NOW)  # one was already made today
    assert foresight.think(log, later) == []


def test_both_predictors_are_scored_on_what_the_boss_actually_does(monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    # The routed summary must use the same clock as the synthetic score data;
    # otherwise this assertion expires when October 1 leaves the 14-day window.
    monkeypatch.setattr(foresight, "datetime", FixedClock)
    log = log_of(CODE_THEN_SPOTIFY)
    settle(log, model="chrome", monkeypatch=monkeypatch)       # she says spotify, the model says chrome
    foresight.moved(log, "spotify", NOW + timedelta(minutes=2))  # the Boss goes to spotify
    t = foresight.tally(NOW)
    assert (t["n"], t["own_hit"], t["model_n"], t["model_hit"], t["agreed"]) == (1, 1, 1, 0, 0)
    assert foresight.trusted(NOW) == "own"
    assert "my own counting: 100% right" in ask("how do your predictions compare").message


def test_the_model_is_believed_only_once_it_has_clearly_done_better(monkeypatch):
    with foresight.knowledge.db() as conn:
        conn.execute("INSERT INTO foresight_tally (day, n, own_hit, model_n, model_hit) VALUES (?, 100, 50, 100, 70)",
                     (NOW.date().isoformat(),))
    assert foresight.trusted(NOW) == "model"
    log = log_of(CODE_THEN_SPOTIFY)
    ((_, subject, data, _),) = foresight.think(log, settle(log, model="whatsapp", monkeypatch=monkeypatch))
    assert subject == "next:code>whatsapp" and data["because"].startswith("my trained model says so")


def test_yes_and_no_are_kept_and_confirmed_guesses_train_the_model():
    log = log_of(CODE_THEN_SPOTIFY)
    ((kind, _, data, _),) = foresight.think(log, settle(log))
    assert foresight.answered(kind, data, "yeah that's right", NOW) == "yes"
    assert foresight.answered(kind, data, "no, wrong this time", NOW) == "no"
    assert foresight.answered(kind, data, "hmm", NOW) is None
    rows = foresight.verified_rows()
    assert len(rows) == foresight.VERIFIED_WEIGHT and rows[0][1:] == ("code", "spotify", None)
    assert "confirmed 1 of my predictions and corrected 1" in foresight.summary(NOW)


def confirm(times, log):
    ((kind, _, data, _),) = foresight.think(log, settle(log))
    for _ in range(times):
        foresight.answered(kind, data, "yes", NOW)


def test_automation_is_offered_only_after_confirmations_and_a_trained_model_that_agrees(monkeypatch):
    log = log_of(CODE_THEN_SPOTIFY)
    confirm(foresight.AUTO_YES, log)
    assert foresight.think(log, settle(log))[0][0] == "prediction"          # no trained model yet: keep asking
    assert foresight.think(log, settle(log, model="chrome", monkeypatch=monkeypatch))[0][0] == "prediction"  # it disagrees
    ((kind, _, data, _),) = foresight.think(log, settle(log, model="spotify", monkeypatch=monkeypatch))
    assert kind == "automate" and data["the_boss_confirmed_it"] == "3 times"
    assert "Shall I just open it myself" in wording.plain({"kind": kind, **data})


@pytest.fixture
def hands(monkeypatch):
    """Let her act for real, with everything she'd touch replaced: (opened, toasts)."""
    opened, toasts = [], []
    monkeypatch.setattr(foresight, "_act", REAL_ACT)  # conftest forbids it
    monkeypatch.setattr("services.activity.log.running_apps", lambda: {"code"})
    monkeypatch.setattr("services.automation.system_control.system.open_app", opened.append)
    monkeypatch.setattr("services.automation.system_control.system.open_url", opened.append)
    monkeypatch.setattr("services.reminders.service.show_toast", lambda title, text, *a: toasts.append(text))
    return opened, toasts


REAL_ACT = foresight._act  # taken at import, before conftest replaces it for each test


def test_once_allowed_she_opens_it_herself_once_a_day_and_can_be_stopped(hands, monkeypatch):
    opened, toasts = hands
    log = log_of(CODE_THEN_SPOTIFY)
    confirm(foresight.AUTO_YES, log)
    later = settle(log, model="spotify", monkeypatch=monkeypatch)
    ((kind, _, data, _),) = foresight.think(log, later)
    foresight.answered(kind, data, "yes do it", NOW)

    assert foresight.think(log, later, busy=True) == [] and opened == []   # never while gaming / fullscreen
    assert foresight.think(log, later) == [] and opened == ["spotify"]
    assert "Opened spotify, Boss" in toasts[0] and log.commands == [{"action": "open_app", "app_name": "spotify", "origin": "automatic"}]
    foresight.think(log, later + timedelta(minutes=5))
    assert opened == ["spotify"]                                            # once a day
    assert "I open by myself: spotify after VS Code" in foresight.summary(NOW)
    assert foresight.stop("spotify") == "Okay, I won't open spotify by myself any more."
    assert foresight.think(log, later + timedelta(days=1)) == []           # and she doesn't ask again


def test_saying_no_to_automation_is_final(monkeypatch):
    log = log_of(CODE_THEN_SPOTIFY)
    confirm(foresight.AUTO_YES, log)
    later = settle(log, model="spotify", monkeypatch=monkeypatch)
    ((kind, _, data, _),) = foresight.think(log, later)
    foresight.answered(kind, data, "no don't", NOW)
    assert foresight.think(log, later) == []


# ── What the Boss starts at this time of day ──────────────────────────────────

SPOTIFY_AT_4 = Habit("time:app:spotify:weekday", "time", ("app:spotify",), 5, 6, 16 * 60, False)


def with_habit(monkeypatch, habit=SPOTIFY_AT_4, running=("code",)):
    monkeypatch.setattr(habits, "learned", lambda log, now: ([habit], {}))
    monkeypatch.setattr(habits, "context", lambda log, now: habits.Context(now, log.app, running=frozenset(running)))
    return log_of([], app="code")


def test_a_time_habit_is_predicted_ahead_of_its_time(monkeypatch):
    log = with_habit(monkeypatch)
    ((kind, subject, data, _),) = foresight.think(log, NOW)  # 3 PM: an hour ahead
    assert (kind, subject) == ("prediction", "next:time:app:spotify:weekday")
    assert wording.plain({"kind": kind, **data}) == \
        "My guess, Boss: around 4:00 PM you'll open spotify (the Boss did on 5 of the last 6 weekdays). Right?"
    assert foresight.think(log, NOW.replace(hour=12)) == []               # too far ahead
    assert foresight.think(log, NOW.replace(hour=15, minute=55)) == []    # too late to call it a prediction
    assert foresight.think(with_habit(monkeypatch, running=("code", "spotify")), NOW) == []  # already open
    assert foresight.think(log, NOW + timedelta(days=2)) == []            # a weekday habit, on a Saturday


def test_a_confirmed_habit_is_handed_over_and_done_at_its_time(hands, monkeypatch):
    opened, toasts = hands
    log = with_habit(monkeypatch)
    ((kind, _, data, _),) = foresight.think(log, NOW)
    for _ in range(foresight.AUTO_YES):
        foresight.answered(kind, data, "yes", NOW)
    assert foresight.verified_rows()[0][1:] == ("code", "spotify", None)   # also an example for the model
    assert foresight.think(log, NOW)[0][0] == "prediction"                 # the model isn't trained yet
    monkeypatch.setattr(learner, "guesses", lambda app, before, when, n=3: ["spotify", "chrome"])
    learner.shadow_path.parent.mkdir(parents=True, exist_ok=True)
    learner.shadow_path.write_bytes(b"trained")
    ((kind, _, data, _),) = foresight.think(log, NOW)
    assert kind == "automate" and "around 4:00 PM you open spotify" in wording.plain({"kind": kind, **data})
    foresight.answered(kind, data, "yes", NOW)
    assert habits.load_state()["habits"][SPOTIFY_AT_4.key]["muted"] is True  # no "Open it?" notification as well

    assert foresight.think(log, NOW) == [] and opened == []                # not before its time
    at_four = NOW.replace(hour=16, minute=2)
    assert foresight.think(log, at_four) == [] and opened == ["spotify"]
    assert "you usually do around 4:00 PM" in toasts[0]
    foresight.think(log, at_four + timedelta(minutes=3))
    assert opened == ["spotify"]
    assert "spotify at its usual time" in foresight.summary(NOW)
    foresight.stop("spotify")
    assert habits.load_state()["habits"][SPOTIFY_AT_4.key]["muted"] is False


def test_a_project_habit_is_predicted_but_never_taken_over(monkeypatch):
    project = Habit("time:project:friday:weekday", "time", ("project:friday",), 5, 6, 16 * 60, False)
    log = with_habit(monkeypatch, project)
    ((kind, _, data, _),) = foresight.think(log, NOW)
    assert kind == "prediction" and data["program"] == "friday" and data["my_trained_model"] == "not trained yet"
    learner.shadow_path.parent.mkdir(parents=True, exist_ok=True)
    learner.shadow_path.write_bytes(b"trained")
    assert foresight.think(log, NOW)[0][2]["my_trained_model"] == "has no opinion on this kind of thing"
    for _ in range(foresight.AUTO_YES):
        foresight.answered(kind, data, "yes", NOW)
    assert foresight.think(log, NOW) == []  # she's sure now, and can't resume a project herself: nothing more to ask


# ── Through the brain ─────────────────────────────────────────────────────────

def test_the_brain_turns_a_guess_into_a_thought_and_the_answer_reaches_foresight():
    log = log_of(CODE_THEN_SPOTIFY)
    log.title = log.project = log.title_since = None
    log.moves = lambda start, end: []
    log.app = "code"
    brain.sense(log, NOW)
    now = NOW + timedelta(minutes=1)
    brain.think(log, now)
    thought = next(t for t in thoughts.alive(now) if t.kind == "prediction")
    assert "you'll open spotify" in wording.plain({"kind": thought.kind, **thought.data})
    brain.answered(thought.id, "yes", now)
    assert len(foresight.verified_rows()) == foresight.VERIFIED_WEIGHT


def test_stop_command_when_nothing_is_automated():
    assert ask("stop opening spotify by yourself").message == "I'm not opening spotify by myself."
