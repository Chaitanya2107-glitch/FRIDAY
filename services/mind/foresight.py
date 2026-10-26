"""
services/mind/foresight.py

FRIDAY predicting what the Boss does next — and earning the right to act on it.

Two predictors, compared by her brain:
  herself    her own counting, no model, from day one: which app follows which
             (services/activity/predict.py) and what the Boss starts at what time of day
             (services/activity/habits.py).
  the model  the nightly-trained one (services/mind/learner.py), once there is enough data to train it.
At every app switch both guess the next app and both are scored against what the Boss actually did
(foresight_tally, per day). When they disagree, the one with the better recent record is believed.

Then the Boss verifies. Once a minute (brain.think) a guess with enough behind it becomes a thought, said
when talking is welcome:
  - "around 10:35 PM you'll open Spotify, right?" — a time habit, said 10 minutes to 2 hours ahead
  - "after X you'll open Y next, right?" — a next-app pattern (plain alt-tabbing back isn't one)
The first prediction of the day needs less behind it, so there's usually at least one. "Yes" / "no" is
kept per pattern, and confirmed ones become extra training examples for the model (foresight_labels).

Automation comes last, and only by asking: a pattern confirmed AUTO_YES times, with her belief in it high,
the model trained, and (for apps) the model agreeing, gets one question — "shall I just do it myself from
now on?" Yes → she opens it herself, once a day, at its time (or a minute after the Boss settles into X),
only if it isn't open already and never while busy, and says so. "stop opening <thing>" ends it.
No → never asked again.

"how do your predictions compare" → summary(). State: three foresight_* tables in memory/mind/brain.db.
"""

import re
from datetime import datetime, timedelta

from core.logger import logger
from services.activity import habits, predict
from services.activity.categories import app_category
from services.activity.habit_patterns import APP_OPEN_AS
from services.mind import knowledge, learner

REBUILD = timedelta(minutes=30)   # her counts are rebuilt from the whole log this often (and kept up in between)
SETTLE_SECONDS = 60               # in an app this long before she predicts from it or acts on it
MIN_SUPPORT = 5                   # times the Boss left this app before, at least
MIN_SHARE, FIRST_SHARE = 0.5, 0.3 # share of those times that went to her guess; the day's first prediction needs less
AHEAD_MINUTES = (10, 120)         # how long before a habit's usual time she says what she expects
ACT_WITHIN_MINUTES = 20           # an automated habit is done from its usual time until this long after
AUTO_YES = 3                      # confirmations before she offers to do it herself …
AUTO_BELIEF = 0.75                # … with (yes+1)/(yes+no+2) at least this
TALLY_DAYS = 14
MODEL_MIN_SCORED, MODEL_MARGIN = 50, 0.02  # the model is believed over her counting only with this much behind it
VERIFIED_WEIGHT = 3               # a confirmed example counts this many times in the nightly training
DULL = {"explorer", "applicationframehost", "shellhost"}  # never worth predicting
FORESIGHT_ACTIONS = {"foresight_summary", "foresight_stop"}

_YES = re.compile(r"\b(?:yes|yeah|yep|yup|ya|right|correct|true|exactly|sure|do it|go ahead|ok|okay|haan)\b", re.I)
_NO = re.compile(r"\b(?:no|nope|nah|wrong|not|don'?t|never|incorrect|nahi)\b", re.I)
_COMPARE = re.compile(r"^(?:how do your predictions compare|who predicts (?:me )?better|compare your predictions"
                      r"|how (?:is|are) your (?:foresight|predictions? (?:doing|going))|what (?:have you|do you) automate[d]?)$", re.I)
_STOP = re.compile(r"^stop (?:opening|launching|starting) (?P<name>[\w .+\-]{2,40}?)"
                   r"(?: (?:by yourself|on your own|yourself|automatically))?$", re.I)

_counts: tuple | None = None   # (Predictor, when it was built)
_pending: dict | None = None   # the app in front and both guesses for what follows it


# ── Two predictors, compared ──────────────────────────────────────────────────

def _predictor(log, now: datetime) -> predict.Predictor:
    global _counts
    if not _counts or now - _counts[1] > REBUILD:
        _counts = (predict.replay(log.app_sequence())[0], now)
    return _counts[0]


def moved(log, app: str, now: datetime) -> None:
    """The app in front changed (brain.sense): score both guesses for the app just left, then guess again."""
    global _pending
    if app_category(app) == "system" or (_pending and _pending["app"] == app):
        return  # system windows aren't choices
    counts = _predictor(log, now)
    before = None
    if _pending:
        _score(_pending, app, now)
        counts.learn(_pending["app"], app, now, _pending["before"])
        before = _pending["app"]
    own = counts.top(app, now, before, 1)
    _pending = {"app": app, "before": before, "at": now, "own": own[0] if own else None,
                "model": learner.guess(app, before, now)}


def _score(guess: dict, went_to: str, now: datetime) -> None:
    own, model = guess["own"], guess["model"]
    if not own:
        return
    agreed = model is not None and own == model
    with knowledge.db() as conn:
        conn.execute("INSERT OR IGNORE INTO foresight_tally (day) VALUES (?)", (now.date().isoformat(),))
        conn.execute("UPDATE foresight_tally SET n = n + 1, own_hit = own_hit + ?, model_n = model_n + ?, "
                     "model_hit = model_hit + ?, agreed = agreed + ?, agreed_hit = agreed_hit + ? WHERE day = ?",
                     (int(own == went_to), int(model is not None), int(model == went_to), int(agreed),
                      int(agreed and own == went_to), now.date().isoformat()))


def tally(now: datetime) -> dict:
    """Both predictors' record over the last TALLY_DAYS days."""
    with knowledge.db() as conn:
        row = conn.execute("SELECT COALESCE(SUM(n), 0) n, COALESCE(SUM(own_hit), 0) own_hit, COALESCE(SUM(model_n), 0) model_n, "
                           "COALESCE(SUM(model_hit), 0) model_hit, COALESCE(SUM(agreed), 0) agreed, "
                           "COALESCE(SUM(agreed_hit), 0) agreed_hit FROM foresight_tally WHERE day >= ?",
                           ((now - timedelta(days=TALLY_DAYS)).date().isoformat(),)).fetchone()
    return dict(row)


def trusted(now: datetime) -> str:
    """Whose guess she goes with when they disagree: "own" unless the model has clearly done better lately."""
    t = tally(now)
    if t["model_n"] >= MODEL_MIN_SCORED and t["n"] and t["model_hit"] / t["model_n"] > t["own_hit"] / t["n"] + MODEL_MARGIN:
        return "model"
    return "own"


def final(guess: dict, now: datetime) -> str | None:
    if guess["model"] and guess["model"] != guess["own"] and trusted(now) == "model":
        return guess["model"]
    return guess["own"] or guess["model"]


# ── Asking the Boss ───────────────────────────────────────────────────────────

def _pattern(conn, key: str, frm: str, thing: str):
    conn.execute("INSERT OR IGNORE INTO foresight_patterns (pattern, frm, nxt) VALUES (?, ?, ?)", (key, frm, thing))
    return conn.execute("SELECT * FROM foresight_patterns WHERE pattern = ?", (key,)).fetchone()


def _asked_today(conn, now: datetime) -> int:
    return conn.execute("SELECT COUNT(*) FROM thoughts WHERE kind = 'prediction' AND at LIKE ?",
                        (now.date().isoformat() + "%",)).fetchone()[0]


def _ask(row, facts: dict, model_agrees: bool | None) -> tuple[str, str, dict, float]:
    """The thought for one guess: a prediction to verify, or — once it has earned it — the offer to take it over.
    model_agrees: None = the model isn't trained yet, or can't judge this kind of thing (a site, a project)."""
    belief = (row["yes"] + 1) / (row["yes"] + row["no"] + 2)
    trained = learner.shadow_path.exists()
    if row["yes"] >= AUTO_YES and belief >= AUTO_BELIEF and trained and model_agrees is not False:
        return ("automate", f"auto:{row['pattern']}", {
            "noticed": "a prediction of mine that the Boss has confirmed several times, and my trained model is ready",
            **facts, "the_boss_confirmed_it": f"{row['yes']} times",
            "ask": "whether I should just do it myself from now on — yes or no"}, 0.7)
    return ("prediction", f"next:{row['pattern']}", {
        "noticed": "I think I know what the Boss will do next", **facts,
        "my_trained_model": {None: "has no opinion on this kind of thing" if trained else "not trained yet",
                             True: "agrees", False: "disagrees"}[model_agrees],
        "ask": "whether that's right — yes or no"}, 0.55)


def think(log, now: datetime, busy: bool = False) -> list[tuple[str, str, dict, float]]:
    """Once a minute: act on what the Boss handed over, and turn her best guess into a thought to verify.
    Returns the thoughts to have: (kind, subject, raw data, strength)."""
    return _habits(log, now, busy) + _next_app(log, now, busy)


def _habits(log, now: datetime, busy: bool) -> list:
    """What the Boss starts at this time of day (her own counting, services/activity/habits.py)."""
    found, _ = habits.learned(log, now)
    minute, today, out = now.hour * 60 + now.minute, now.date().isoformat(), []
    due = [h for h in found if h.kind == "time" and h.weekend == (now.weekday() >= 5)
           and -ACT_WITHIN_MINUTES <= h.minute - minute <= AHEAD_MINUTES[1]]
    if not due:
        return []
    ctx = habits.context(log, now)
    for h in sorted(due, key=lambda h: -h.support):
        thing = h.things[0]
        kind, name = thing.split(":", 1)
        ahead = h.minute - minute
        with knowledge.db() as conn:
            row = _pattern(conn, h.key, "time", thing)
            first = not _asked_today(conn, now)
        if habits.is_open(thing, ctx) or row["auto"] == -1 or (kind == "project" and row["yes"] >= AUTO_YES):
            continue  # already open, declined, or a project she's sure of (she can't resume those herself)
        if row["auto"] == 1:
            if ahead <= 0 and row["last_run"] != today and not busy and kind != "project":
                _act(log, row, now, f"you usually do around {habits._clock(h.minute)}")
            continue
        if ahead < AHEAD_MINUTES[0] or h.support < (FIRST_SHARE if first else MIN_SHARE) or out:
            continue
        guesses = learner.guesses(log.app, None, now.replace(hour=h.minute // 60, minute=h.minute % 60), predict.TOP) \
            if kind == "app" and log.app else None
        out.append(_ask(row, {
            "program": habits._name(thing), "around": habits._clock(h.minute),
            "because": f"the Boss did on {h.days} of the last {h.observed} {'weekend days' if h.weekend else 'weekdays'}",
            "context": {"pattern": h.key, "frm": log.app, "thing": thing,
                        "at": now.replace(hour=h.minute // 60, minute=h.minute % 60, second=0, microsecond=0).isoformat()},
        }, None if guesses is None else name in guesses))
    return out


def _next_app(log, now: datetime, busy: bool) -> list:
    """Which app follows the one in front (her counting against the model)."""
    guess = _pending
    if not guess or (now - guess["at"]).total_seconds() < SETTLE_SECONDS or log.app != guess["app"]:
        return []
    frm, nxt = guess["app"], final(guess, now)
    if not nxt or nxt in DULL or nxt == guess["before"] or app_category(nxt) == "system":
        return []  # nothing, or just alt-tabbing back: not a prediction worth anyone's time
    with knowledge.db() as conn:
        row = _pattern(conn, f"{frm}>{nxt}", frm, f"app:{nxt}")
        first = not _asked_today(conn, now)
    if row["auto"] == 1:
        if row["last_run"] != now.date().isoformat() and not busy:
            _act(log, row, now, f"you usually do after {habits._name('app:' + frm)}")
        return []
    if row["auto"] == -1:
        return []
    after = _predictor(log, now).after[frm]
    went, left = after[nxt], sum(after.values())
    by_model = nxt != guess["own"]  # the trained model's guess, believed because its record is better
    if not by_model and (left < MIN_SUPPORT or went / left < (FIRST_SHARE if first else MIN_SHARE)):
        return []
    return [_ask(row, {
        "after": habits._name(f"app:{frm}"), "program": habits._name(f"app:{nxt}"),
        "because": "my trained model says so, and lately it has been right more often than my own counting" if by_model
        else f"{went} of the {left} times the Boss left {habits._name('app:' + frm)}, they went there",
        "context": {"pattern": row["pattern"], "frm": frm, "thing": f"app:{nxt}", "before": guess["before"],
                    "at": guess["at"].isoformat(timespec="seconds")},
    }, None if guess["model"] is None else guess["model"] == nxt)]


def answered(kind: str, data: dict, answer: str, now: datetime) -> str | None:
    """The Boss's yes / no to a prediction or to the offer to automate it. Returns what it was taken as."""
    context = data.get("context") or {}
    said = "no" if _NO.search(answer) else "yes" if _YES.search(answer) else None
    if not context or not said:
        return None
    key, thing = context["pattern"], context["thing"]
    with knowledge.db() as conn:
        if kind == "automate":
            conn.execute("UPDATE foresight_patterns SET auto = ? WHERE pattern = ?", (1 if said == "yes" else -1, key))
        else:
            conn.execute(f"UPDATE foresight_patterns SET {said} = {said} + 1 WHERE pattern = ?", (key,))
            if thing.startswith("app:") and context.get("frm"):  # something the model can learn from
                conn.execute("INSERT INTO foresight_labels (at, frm, before, nxt, right, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                             (context["at"], context["frm"], context.get("before"), thing[4:], int(said == "yes"),
                              now.isoformat(timespec="seconds")))
    if kind == "automate" and key.startswith("time:"):
        _mute_suggestion(key, said == "yes")  # she does it herself now: no "Open it?" notification as well
    logger.info(f"Foresight: {kind} {key} → {said}")
    return said


def _mute_suggestion(habit_key: str, muted: bool) -> None:
    state = habits.load_state()
    habits._record(state, habit_key)["muted"] = muted
    habits._save_state(state)


def verified_rows() -> list[tuple[datetime, str, str, str | None]]:
    """Predictions the Boss confirmed, as training rows for the nightly model: (when, from, to, the app before)."""
    with knowledge.db() as conn:
        rows = conn.execute("SELECT at, frm, nxt, before FROM foresight_labels WHERE right = 1").fetchall()
    return [(datetime.fromisoformat(r["at"]), r["frm"], r["nxt"], r["before"]) for r in rows] * VERIFIED_WEIGHT


# ── Acting ────────────────────────────────────────────────────────────────────

def _act(log, row, now: datetime, why: str) -> None:
    """An automated pattern's moment: open it (if it isn't running), say so, and not again today."""
    # ponytail: apps and sites only; a project (terminal + folder + sites) still needs its "resume" command
    from services.activity.log import running_apps
    from services.automation.system_control import system
    from services.reminders.service import show_toast

    with knowledge.db() as conn:
        conn.execute("UPDATE foresight_patterns SET last_run = ? WHERE pattern = ?", (now.date().isoformat(), row["pattern"]))
    kind, name = row["nxt"].split(":", 1)
    if kind == "app" and name in running_apps():
        return
    try:
        from services.learning import origin
        with origin.action_scope("automatic"):
            system.open_url(f"https://{name}") if kind == "site" else system.open_app(APP_OPEN_AS.get(name, name))
    except Exception as e:  # her own initiative must never break the minute
        logger.warning(f"Foresight couldn't open {name}: {e}")
        return
    command = {"action": "open_app", "app_name": name} if kind == "app" else {"action": "open_url", "url": name}
    log.log_command({**command, "origin": "automatic"}, True)
    shown = habits._name(row["nxt"])
    show_toast("F.R.I.D.A.Y", f"Opened {shown}, Boss — {why}. Say \"stop opening {shown}\" and I won't.")
    logger.info(f"Foresight: opened {name} by herself ({row['pattern']})")


# ── Commands ──────────────────────────────────────────────────────────────────

def match_foresight_command(text: str) -> dict | None:
    text = text.strip(" ?!.")
    if _COMPARE.match(text):
        return {"type": "system", "action": "foresight_summary"}
    if m := _STOP.match(text):
        return {"type": "system", "action": "foresight_stop", "name": m["name"].lower()}
    return None


def stop(name: str) -> str:
    with knowledge.db() as conn:
        rows = [r for r in conn.execute("SELECT * FROM foresight_patterns WHERE auto = 1")
                if name in (r["nxt"].split(":", 1)[1], habits._name(r["nxt"]).lower(), APP_OPEN_AS.get(r["nxt"].split(":", 1)[1]))]
        for r in rows:
            conn.execute("UPDATE foresight_patterns SET auto = -1 WHERE pattern = ?", (r["pattern"],))
    for r in rows:
        if r["pattern"].startswith("time:"):
            _mute_suggestion(r["pattern"], False)
    return f"Okay, I won't open {name} by myself any more." if rows else f"I'm not opening {name} by myself."


def summary(now: datetime | None = None) -> str:
    now = now or datetime.now()
    t = tally(now)
    pct = lambda hit, n: f"{round(100 * hit / n)}%"
    lines = [f"Guessing your next app, last {TALLY_DAYS} days, checked against what you did ({t['n']} switches):",
             f"- my own counting: {pct(t['own_hit'], t['n'])} right" if t["n"] else "- my own counting: no score yet",
             f"- the trained model: {pct(t['model_hit'], t['model_n'])} right" if t["model_n"]
             else "- the trained model: trained, no score yet" if learner.shadow_path.exists()
             else "- the trained model: not trained yet (it trains itself at night once there's enough to learn from)"]
    if t["agreed"]:
        lines.append(f"- when the two agreed ({pct(t['agreed'], t['model_n'])} of the time): {pct(t['agreed_hit'], t['agreed'])} right")
    lines.append(f"When they disagree I go with {'the trained model' if trusted(now) == 'model' else 'my own counting'}.")
    with knowledge.db() as conn:
        yes, no = conn.execute("SELECT COALESCE(SUM(yes), 0), COALESCE(SUM(no), 0) FROM foresight_patterns").fetchone()
        auto = [habits._name(r["nxt"]) + (f" after {habits._name('app:' + r['frm'])}" if r["frm"] != "time" else " at its usual time")
                for r in conn.execute("SELECT frm, nxt FROM foresight_patterns WHERE auto = 1")]
    lines.append(f"You've confirmed {yes} of my predictions and corrected {no}.")
    lines.append("I open by myself: " + ", ".join(auto) + "." if auto else "Nothing is automated yet: I'll ask first.")
    return "\n".join(lines)


def run(parsed: dict) -> str:
    return stop(parsed["name"]) if parsed["action"] == "foresight_stop" else summary()
