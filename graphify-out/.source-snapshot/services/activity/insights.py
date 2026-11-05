"""
services/activity/insights.py

Numbers about the user, from the local logs (counting, no AI):
  - "how good are your suggestions"   → habit suggestions shown / used / not now / ignored, by kind
                                        and time of day (memory/habit_examples.jsonl)
  - "when do I usually start / stop"  → typical first and last activity (a day runs 5 AM–5 AM);
                                        also a "Rhythm" line in the weekly summary
  - "when do I study best"            → study sessions by starting time: how many, how long
  - "how long will this session last" → the running session against past ones of its kind
                                        started around the same time
  - deadline risk (briefing only): a deadline within RISK_DAYS for a subject with under
    RISK_MINUTES of study in the last 3 days
  - memory/command_examples.jsonl, rewritten each night with the journal: one row per command
    (hour, weekday, app in front, action, target, success, the previous command and how long
    before) — training data next to the habit and command-bar examples
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

from core.config import config
from services.activity import sessions
from services.activity.log import _duration

commands_path = config.MEMORY_DIR / "command_examples.jsonl"  # tests point this elsewhere
DAY_STARTS_HOUR = 5
RISK_DAYS, RISK_MINUTES = 5, 30
INSIGHT_ACTIONS = {"suggestion_score", "day_hours", "best_study", "session_forecast"}
PARTS = [(5, 12, "mornings"), (12, 17, "afternoons"), (17, 21, "evenings"), (21, 29, "nights")]

_SCORE = re.compile(r"^how (?:good|useful|accurate) (?:are|were) (?:your|the) (?:habit )?suggestions$", re.I)
_DAY = re.compile(r"^when do i (?:usually |normally )?(?:start|stop|wake up|go to (?:bed|sleep)|sleep)(?: (?:my day|working|using the laptop))?"
                  r"$|^(?:what are )?my (?:usual )?(?:day|laptop|active) hours$", re.I)
_BEST = re.compile(r"^when do i study best$|^(?:what(?:'s| is) )?my best (?:time|hours?) (?:to|for) study(?:ing)?$", re.I)
_FORECAST = re.compile(r"^how (?:long|much longer) will (?:this|my|the) (?:session|study session|work session) (?:last|go on)$", re.I)


def match_insight_command(text: str) -> dict | None:
    text = text.strip().rstrip("?.!")
    for pattern, action in ((_SCORE, "suggestion_score"), (_DAY, "day_hours"), (_BEST, "best_study"),
                            (_FORECAST, "session_forecast")):
        if pattern.match(text):
            return {"type": "system", "action": action}
    return None


def run(parsed: dict, log, now: datetime | None = None) -> str:
    now = now or datetime.now()
    return {"suggestion_score": lambda: suggestion_score(), "day_hours": lambda: day_hours(log, now),
            "best_study": lambda: best_study(log, now), "session_forecast": lambda: session_forecast(log, now)}[
        parsed["action"]]()


def _clock(minute: int) -> str:
    minute %= 24 * 60
    return datetime(2000, 1, 1, minute // 60, minute % 60).strftime("%I:%M %p").lstrip("0")


def _part(hour: int) -> str:
    hour = hour if hour >= DAY_STARTS_HOUR else hour + 24
    return next(name for start, end, name in PARTS if start <= hour < end)


# ── Suggestions ───────────────────────────────────────────────────────────────

def suggestion_score() -> str:
    from services.activity import habits

    try:
        lines = [json.loads(x) for x in habits.examples_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        lines = []
    shown = {x["id"]: x for x in lines if "habit" in x}
    answers = {x["id"]: x["answer"] for x in lines if "answer" in x}
    if not shown:
        return "I haven't made any habit suggestions yet."
    used = [s for sid, s in shown.items() if answers.get(sid) == "do"]
    by_kind: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_part: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for sid, s in shown.items():
        for table, key in ((by_kind, s["habit"].split(":")[0]), (by_part, _part(datetime.fromisoformat(s["at"]).hour))):
            table[key][0] += answers.get(sid) == "do"
            table[key][1] += 1
    tally = {a: sum(1 for sid in shown if answers.get(sid) == a) for a in ("later", "never", "ignored")}
    kinds = ", ".join(f"{k} {u}/{n}" for k, (u, n) in by_kind.items())
    best = max(by_part.items(), key=lambda i: (i[1][0] / i[1][1], i[1][1]))
    return (f"Habit suggestions: {len(shown)} shown, {len(used)} used ({round(100 * len(used) / len(shown))}%), "
            f"{tally['later']} not now, {tally['never']} stopped, {tally['ignored']} ignored. By kind: {kinds}. "
            f"Best in the {best[0]} ({best[1][0]}/{best[1][1]}).")


# ── Day hours ─────────────────────────────────────────────────────────────────

def day_edges(rows) -> dict:
    """(at, seconds, …) rows → {day: (first minute, last minute)}; a day runs 5 AM–5 AM, so 1:30 AM is minute 1530."""
    edges: dict = {}
    for at, seconds, *_ in rows:
        start = at if isinstance(at, datetime) else datetime.fromisoformat(at)
        end = start + timedelta(seconds=seconds or 0)
        day = (start - timedelta(hours=DAY_STARTS_HOUR)).date()
        base = datetime.combine(day, datetime.min.time())
        first, last = (start - base).total_seconds() // 60, (end - base).total_seconds() // 60
        old = edges.get(day, (first, last))
        edges[day] = (min(old[0], first), max(old[1], last))
    return edges


def rhythm_line(rows) -> str | None:
    """ "usually started around 9:10 AM and stopped around 1:30 AM" — None under 3 days."""
    edges = list(day_edges(rows).values())
    if len(edges) < 3:
        return None
    return (f"usually started around {_clock(int(median(e[0] for e in edges)))} and stopped around "
            f"{_clock(int(median(e[1] for e in edges)))}")


def day_hours(log, now: datetime, days: int = 14) -> str:
    line = rhythm_line(log.app_rows(now - timedelta(days=days), now))
    return f"Over the last {days // 7} weeks you {line}." if line else "I need at least 3 days of activity for that."


# ── Study and sessions ────────────────────────────────────────────────────────

def _past_sessions(log, now: datetime, days: int = 28) -> list:
    return sessions.build(log.app_rows(now - timedelta(days=days), now))


def best_study(log, now: datetime) -> str:
    study = [s for s in _past_sessions(log, now) if s.group == "study"]
    if len(study) < 3:
        return "I need a few more study sessions (on study sites and apps) to tell."
    by_part: dict[str, list[float]] = defaultdict(list)
    for s in study:
        by_part[_part(s.start.hour)].append(s.active_s)
    ranked = sorted(by_part.items(), key=lambda i: -sum(i[1]) / len(i[1]))
    best, worst = ranked[0], ranked[-1]
    line = (f"Your longest study sessions are in the {best[0]}: {len(best[1])} sessions, "
            f"{_duration(sum(best[1]) / len(best[1]))} on average")
    if worst[0] != best[0]:
        line += f"; the shortest in the {worst[0]} ({_duration(sum(worst[1]) / len(worst[1]))})"
    return line + "."


def session_forecast(log, now: datetime) -> str:
    running = [s for s in sessions.recent(log, now) if now - s.end <= sessions.GAP]
    if not running:
        return "You're not in a session right now."
    current = max(running, key=lambda s: s.active_s)
    so_far = (now - current.start).total_seconds()
    past = [s for s in _past_sessions(log, now) if s.group == current.group and s.start < current.start
            and abs(s.start.hour - current.start.hour) <= 2]
    doing = sessions.DOING[current.group]
    if len(past) < 3:
        return f"You've been {doing} for {_duration(so_far)}. I haven't seen enough {current.group} sessions around this time to guess."
    usual = median((s.end - s.start).total_seconds() for s in past)
    left = usual - so_far
    tail = f"about {_duration(left)} to go" if left > 60 else "you're past your usual length"
    return f"You've been {doing} for {_duration(so_far)}; around this time it usually lasts {_duration(usual)} — {tail}."


# ── Deadline risk ─────────────────────────────────────────────────────────────

def deadline_risk_line(log, now: datetime) -> str:
    """For the briefing: deadlines close by whose subject has barely been studied lately. "" if none."""
    from services.activity import study
    from services.proactive import deadlines, timetable

    risky = []
    for d in deadlines.load():
        due = datetime.fromisoformat(d["due"])
        if not timedelta(0) < due - now <= timedelta(days=RISK_DAYS):
            continue
        subject = next((s for s in timetable.subjects() if timetable.mentions_subject(d["what"], timetable.aliases(s))), None)
        if not subject:
            continue
        minutes = study.totals(log.study_rows(now - timedelta(days=3), now), [subject]).get(subject, 0) / 60
        if minutes < RISK_MINUTES:
            risky.append(f"{d['what']} is due in {(due.date() - now.date()).days or 'under a'} day"
                         f"{'s' if (due.date() - now.date()).days != 1 else ''} with {round(minutes)} min of {subject} "
                         "in the last 3 days")
    return ("Heads up: " + "; ".join(risky) + ".") if risky else ""


# ── Command dataset ───────────────────────────────────────────────────────────

def write_command_dataset(log) -> int:
    """Rewrite memory/command_examples.jsonl from every command in the log. Returns the number of rows."""
    rows = log.command_rows()
    previous, lines = None, []
    for r in rows:
        at = datetime.fromisoformat(r["at"])
        lines.append(json.dumps({
            "at": r["at"], "hour": at.hour, "weekday": at.weekday(), "app_in_front": r["app"], "action": r["action"],
            "target": r["target"], "success": r["success"], "previous_action": previous["action"] if previous else None,
            "minutes_since_previous": round((at - datetime.fromisoformat(previous["at"])).total_seconds() / 60)
            if previous else None}))
        previous = r
    commands_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)
