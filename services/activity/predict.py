"""
services/activity/predict.py

The shadow predictor: a first, measured step toward FRIDAY predicting your moves. It never
shows a guess on its own. It learns which app you switch to next — from the app you're in,
the hour and the weekday — and is scored by replaying the activity log in order: at each
switch it guesses using only what came before, then checks. Counts only, no AI, all local.
  "how good are your predictions" → hit rates per week, against a naive guess
                                    (back to the app you were in before this one)
  "what will I open next"         → its current top 3
  "how good are your bar guesses" → how often the command bar's guesses were used
The weekly summary gets one line of the same numbers. The habit engine can build on Predictor.

The command bar (Ctrl+Shift+F) shows guesses when it opens empty — habits due now, then the next
app from here (bar_suggestions); Tab puts one in the box. Each opening that showed guesses is
saved as a labelled example in memory/bar_predictions.jsonl (bar_outcome): the data for ML 2.0.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from core.config import config
from core.logger import logger

bar_log_path = config.MEMORY_DIR / "bar_predictions.jsonl"  # tests point this elsewhere
PREDICT_ACTIONS = {"prediction_accuracy", "predict_next", "bar_score"}
TOP = 3
MIN_SWITCHES = 20  # fewer scored switches in a week than this: not worth a number
HOUR_WEIGHT, SLOT_WEIGHT = 2.0, 0.3
BACK = "<back>"  # "back to the app before this one" is learned as its own choice (alt-tab habit)

_ACCURACY = re.compile(r"^(?:how (?:good|accurate|well) (?:are|do) (?:your|you) (?:predictions?|predict(?:ing)?)"
                       r"|(?:show |what(?:'s| is|are) )?(?:your |my )?prediction (?:accuracy|score|stats)"
                       r"|how good are you at predicting(?: me| what i do)?)$", re.I)
_NEXT = re.compile(r"^(?:what (?:will|would|do you think) i(?:'ll)? (?:open|use|do)(?: next)?|what(?:'s| is) my next app"
                   r"|guess what i(?:'ll| will) open next|predict (?:my )?next app)$", re.I)
_BAR = re.compile(r"^how (?:good|accurate) (?:are|were) (?:your|the) (?:command )?bar (?:guesses|suggestions|predictions)$", re.I)


def match_predict_command(text: str) -> dict | None:
    text = text.strip()
    if _BAR.match(text):
        return {"type": "system", "action": "bar_score"}
    if _ACCURACY.match(text):
        return {"type": "system", "action": "prediction_accuracy"}
    if _NEXT.match(text):
        return {"type": "system", "action": "predict_next"}
    return None


def _slot(when: datetime) -> tuple[bool, int]:
    return when.weekday() >= 5, when.hour  # weekend or not, hour


class Predictor:
    """Next-app counts: after `app`, overall / around this hour / at this time of the week."""

    def __init__(self):
        self.after: dict[str, Counter] = defaultdict(Counter)
        self.after_at_hour: dict[tuple, Counter] = defaultdict(Counter)
        self.at_slot: dict[tuple, Counter] = defaultdict(Counter)

    def top(self, app: str, when: datetime, before: str | None = None, n: int = TOP) -> list[str]:
        scores: Counter = Counter()
        for weight, counts in ((1.0, self.after[app]), (HOUR_WEIGHT, self.after_at_hour[(app, when.hour)]),
                               (SLOT_WEIGHT, self.at_slot[_slot(when)])):
            for nxt, count in counts.items():
                scores[nxt] += weight * count
        back = scores.pop(BACK, 0)
        if before:
            scores[before] += back
        scores.pop(app, None)  # a switch always goes somewhere else
        return [nxt for nxt, _ in scores.most_common(n)]

    def learn(self, app: str, nxt: str, when: datetime, before: str | None = None) -> None:
        nxt = BACK if nxt == before else nxt
        self.after[app][nxt] += 1
        self.after_at_hour[(app, when.hour)][nxt] += 1
        self.at_slot[_slot(when)][nxt] += 1


def switches(sequence: list[tuple[str, str]]) -> list[tuple[datetime, str, str, str | None]]:
    """(at, app) rows → (when, from, to, the app before `from`); a new title in the same app isn't a switch."""
    apps: list[tuple[datetime, str]] = []
    for at, app in sequence:
        if not apps or apps[-1][1] != app:
            apps.append((datetime.fromisoformat(at), app))
    return [(apps[i][0], apps[i - 1][1], apps[i][1], apps[i - 2][1] if i >= 2 else None) for i in range(1, len(apps))]


def replay(sequence: list[tuple[str, str]]) -> tuple[Predictor, dict[date, dict]]:
    """Score every switch with only earlier data. Returns the trained predictor and per-week tallies."""
    predictor, weeks = Predictor(), {}
    for when, app, nxt, before in switches(sequence):
        week = weeks.setdefault(when.date() - timedelta(days=when.weekday()), {"n": 0, "top1": 0, "top3": 0, "naive": 0})
        guesses = predictor.top(app, when, before)
        if guesses:  # nothing known about this app yet: not scored
            week["n"] += 1
            week["top1"] += guesses[0] == nxt
            week["top3"] += nxt in guesses
            week["naive"] += before == nxt
        predictor.learn(app, nxt, when, before)
    return predictor, weeks


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%"


def week_line(week: dict | None) -> str | None:
    if not week or week["n"] < MIN_SWITCHES:
        return None
    return (f"{_pct(week['top1'], week['n'])} right first guess, {_pct(week['top3'], week['n'])} in the top 3 "
            f"(naive guess {_pct(week['naive'], week['n'])}; {week['n']} app switches)")


def accuracy(log) -> str:
    _, weeks = replay(log.app_sequence())
    lines = [f"Week of {monday:%d %b}: {line}" for monday, week in sorted(weeks.items()) if (line := week_line(week))]
    if not lines:
        return "Not enough activity yet to score my predictions."
    return "My app predictions, checked against what you actually did:\n" + "\n".join(lines)


def predict_next(log, now: datetime | None = None) -> str:
    sequence = log.app_sequence()
    if not sequence:
        return "I haven't seen enough of your activity yet."
    predictor, _ = replay(sequence)
    last = switches(sequence)[-1:] or [(None, None, sequence[-1][1], None)]
    _, before, current, _ = last[0]  # the app in use now, and the one before it
    guesses = _guesses(predictor, current, before, now or datetime.now())
    if not guesses:
        return f"I don't know yet what you usually do after {current}."
    return f"After {current}, my guess is {guesses[0]}" + (f", then {' or '.join(guesses[1:])}." if len(guesses) > 1 else ".")


def _guesses(predictor: Predictor, app: str, before: str | None, when: datetime, n: int = TOP) -> list[str]:
    """The nightly-trained model's guesses while it beats counting (services/mind/learner.py), else counting's."""
    from services.mind import learner  # it builds on this module: import late
    from services.mind.prediction_review import rank

    guesses = learner.top(app, before, when, n) or predictor.top(app, when, before, n)
    return rank(guesses, app, before, when)[:n]


def run(parsed: dict, log) -> str:
    if parsed["action"] == "bar_score":
        return bar_score()
    return accuracy(log) if parsed["action"] == "prediction_accuracy" else predict_next(log)


# ── The command bar's guesses ─────────────────────────────────────────────────

def bar_suggestions(log, now: datetime | None = None) -> list[str]:
    """Up to TOP commands to offer when the command bar opens empty: habits due now first, then where you
    usually switch next from the app you were in ("resume catjang", "open spotify", "go to github.com")."""
    from services.activity import habits  # habits builds on this module's neighbours; import late
    from services.activity.habit_patterns import NOT_APPS

    now = now or datetime.now()
    offered = []
    try:
        offered += [habits.command_for(h.things[-1]) for h in habits.due_now(log, now)]
    except Exception as e:  # a guess must never break the bar
        logger.info(f"Bar suggestions: habits skipped: {e}")
    sequence = log.app_sequence()
    if sequence:
        predictor, _ = replay(sequence)
        last = switches(sequence)[-1:] or [(None, None, sequence[-1][1], None)]
        _, before, current, _ = last[0]
        offered += [habits.command_for(f"app:{app}") for app in _guesses(predictor, current, before, now, TOP * 2)
                    if app not in NOT_APPS - {"chrome", "msedge"}]  # browsers are fine to switch to
    return list(dict.fromkeys(offered))[:TOP]


def bar_outcome(offered: list[str], sent: str | None, log, now: datetime | None = None) -> None:
    """One labelled example per bar opening that showed guesses: which one was used, or that the user typed
    something else (not what) or closed the bar — training data next to the habit examples."""
    if not offered:
        return
    now = now or datetime.now()
    picked = offered.index(sent) if sent in offered else -1
    line = {"at": now.isoformat(timespec="seconds"), "offered": offered, "picked": picked,
            "outcome": "picked" if picked >= 0 else "typed" if sent else "closed",
            "hour": now.hour, "weekday": now.weekday(), "app_before": log.last_app}
    try:
        with bar_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError as e:
        logger.warning(f"Couldn't save a command bar example: {e}")


def bar_score(now: datetime | None = None) -> str:
    """ "how good are your bar guesses": how often an offered command was used."""
    try:
        lines = [json.loads(x) for x in bar_log_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        lines = []
    shown = [x for x in lines if x["outcome"] != "closed"]
    if not shown:
        return "No command bar guesses used or skipped yet."
    picked = sum(x["picked"] >= 0 for x in shown)
    first = sum(x["picked"] == 0 for x in shown)
    return (f"Command bar guesses: used {picked} of {len(shown)} times ({_pct(picked, len(shown))}), "
            f"the first guess {first} times.")
