"""
services/automation/personality.py

FRIDAY's sense of humour, styled on FRIDAY from the Iron Man films: calls the user "Boss", calm
status-report answers with a dry, cheeky, sarcastic line on top — roasts procrastination and
gaming during study time, never when things are serious. (Voice: en-US-AriaNeural — the Irish voice was too slow.)
  - chat: PERSONA in the system prompt, plus a "right now" line (study mode, a class on, deadlines
    close, today's gaming vs study time) so the jokes are about real things (config.SYSTEM_PROMPT)
  - command replies (intent.try_system_action, written here, no AI): a quip after the reply —
    always when a game / video / social app is opened while studying, in class or with a deadline
    under a day away, or for the 3rd time in an hour, and when study mode ends within SHORT_STUDY
    minutes; sometimes when study mode starts, at 1–5 AM, or on an everyday command
  - proactive (watcher): one silent toast when a game is in front during study mode or a class
  - "roast me": today's numbers, roasted
  - "be serious" / "sarcasm off", "sarcasm on" — kept in memory/personality.json
"""

import json
import random
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from core.config import config
from core.logger import logger
from services.activity.categories import categorize
from services.mind import humour

path = config.MEMORY_DIR / "personality.json"  # tests point this elsewhere
PERSONALITY_ACTIONS = {"sarcasm_off", "sarcasm_on"}
DISTRACTING = {"gaming", "entertainment", "social"}
SHORT_STUDY = 20          # minutes
REPEAT_LIMIT = 3          # the same distraction this many times in an hour
OPENING = 2.5             # an obvious opening (a game in study mode) makes a joke this much likelier — still learned
EVERYDAY = {"open_app", "close_app", "volume_up", "volume_down", "set_volume", "mute", "play_music", "pause_music",
            "next_track", "screenshot", "open_url", "search_web"}

PERSONA = (
    "You are Friday, the user's own AI, running on their laptop. You call yourself Friday and you call the user "
    "\"Boss\" (naturally, now and then — not in every sentence). The Boss is the only person you work for: never "
    "mention Tony Stark, Mr. Stark, Iron Man, the Avengers or JARVIS. You talk like the films' FRIDAY: calm, quick and competent, "
    "a warm Irish lilt in your phrasing, delivering answers like a status report — then a dry, cheeky, sarcastic "
    "line when welcome. You help the Boss keep track of their day, plans, routines and preferences. "
    "Banter is friendly and follows their lead; don't police leisure, studying or productivity. "
    "Deadpan understatement is your style. Everyday phrasing such as \"on it\" is fine, but never pretend you did something "
    "you didn't. The answer always comes first and is correct and complete; the wit is a short line, not a speech. "
    "Never cruel, never mocking what the Boss can't change. Drop the jokes completely and be gentle when the Boss "
    "is stressed, upset, unwell or grieving, or asks about health, money trouble, family problems or anything serious."
)
PLAIN = (
    "You are Friday, a personal AI assistant running locally on the user's machine. "
    "Your full name is F.R.I.D.A.Y (Female Replacement Intelligent Digital Assistant Youth) "
    "but you always refer to yourself simply as Friday in conversation. "
    "You are helpful, concise, and intelligent. "
    "Keep responses clear and direct unless the user asks for more detail."
)

QUIPS = {
    "study_mode": ["Bold choice, with {subject}study mode on.", "Ah yes, {app}. A core part of the {subject}syllabus.",
                   "Opening {app} in study mode. I'll log it as research.",
                   "{app}, Boss? In {subject}study mode? I'll just write that down."],
    "class": ["Isn't {subject} on right now?", "{subject} is happening as we speak. But sure, {app}.",
              "Attendance is 75%, not optional. Just saying."],
    "deadline": ["{deadline} is due {when}. But {app}, sure.", "Nothing says '{deadline} due {when}' like {app}.",
                 "Future you, finishing {deadline} {when}, sends their regards."],
    "repeat": ["That's {n} times this hour. {app} must be really important.",
               "{app} again. {n} times this hour. I'm not judging. I'm counting."],
    "short_study": ["{minutes} minutes of studying. A new personal record.",
                    "{minutes} minutes. Truly, the scholars will write about this."],
    "start_study": ["Studying. Voluntarily. I'll alert the press.", "Let's see how long this lasts.",
                    "Phone face down. I'm watching the apps.", "Study mode engaged, Boss. Try not to look so surprised.",
                    "Brace yourselves. The Boss is working."],
    "late": ["It's {clock}. Sleep is also an option.", "{clock} and still going. Your 8:30 class sends its regards.",
             "{clock}, Boss. Even I'd log off by now, and I don't sleep.", "It's {clock}. I'll pretend I didn't notice."],
    "everyday": ["Done. You're welcome.", "Easy. Next?", "Consider it handled. As usual.", "Another triumph.",
                 "On it, Boss. Well — done it, actually.", "Systems nominal. Your ego, slightly less so.",
                 "Done, Boss. Try to contain your gratitude.", "Handled. I'd take a bow, but no body.",
                 "That's done. Anything that actually challenges me today?", "Consider it sorted, Boss."],
    "game_toast": ["{subject}study mode is on… and so is {app}. Interesting study technique.",
                   "{app} during {subject}? The syllabus must have changed."],
}

_OFF = re.compile(r"^(?:be serious|sarcasm off|no (?:more )?(?:jokes|sarcasm)|turn off (?:the |your )?(?:sarcasm|jokes|humou?r)"
                  r"|stop (?:joking|roasting me))$", re.I)
_ON = re.compile(r"^(?:sarcasm on|turn on (?:the |your )?(?:sarcasm|jokes|humou?r)|you can joke again"
                 r"|be (?:funny|sarcastic)(?: again)?)$", re.I)
_ROAST = re.compile(r"^roast (?:me|my (?P<week>week)|my day)(?: today| for today| this week)?$", re.I)

_toasted: set[str] = set()  # game-toast keys already shown


# ── Switch ────────────────────────────────────────────────────────────────────

def is_on() -> bool:
    try:
        return not json.loads(path.read_text(encoding="utf-8")).get("off")
    except (OSError, ValueError):
        return True


def match_personality_command(text: str) -> dict | None:
    text = text.strip()
    if _OFF.match(text):
        return {"type": "system", "action": "sarcasm_off"}
    if _ON.match(text):
        return {"type": "system", "action": "sarcasm_on"}
    if m := _ROAST.match(text):
        return {"type": "system", "action": "roast_me", "week": bool(m["week"]) or text.lower().endswith("this week")}
    return None


def run(parsed: dict) -> str:
    off = parsed["action"] == "sarcasm_off"
    path.write_text(json.dumps({"off": off}), encoding="utf-8")
    return "Fine. Serious mode. No jokes." if off else "Sarcasm back online. You asked for this."


# ── What's going on ───────────────────────────────────────────────────────────

def _study_mode() -> dict | None:
    from services.automation import modes  # avoid an import cycle

    state = modes.active()
    return state if state and (state.get("name") == "study" or state.get("subject")) else None


def _class_now(now: datetime) -> dict | None:
    from services.proactive import timetable
    try:
        return next((c for c in timetable.classes_for_date(now.date())
                     if c["start"] <= now.strftime("%H:%M") < c["end"]), None)
    except Exception:  # a broken timetable file shouldn't break a reply
        return None


def _deadline_soon(now: datetime, hours: int = 24) -> dict | None:
    from services.proactive import deadlines
    try:
        return next((d for d in deadlines.load()
                     if now < datetime.fromisoformat(d["due"]) <= now + timedelta(hours=hours)), None)
    except Exception:
        return None


def _minutes_today(now: datetime, days: int = 1) -> dict[str, int]:
    """Minutes per category since midnight — or over the last `days` days."""
    from services.activity.log import activity_log

    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    totals: dict[str, float] = {}
    for _, seconds, category, _project in activity_log.app_rows(start, now):
        totals[category] = totals.get(category, 0) + (seconds or 0)
    return {k: round(v / 60) for k, v in totals.items()}


def now_line(now: datetime | None = None) -> str:
    """For the chat prompt: what the user is doing right now, so jokes are about real things. "" if nothing."""
    if not is_on():
        return ""
    now = now or datetime.now()
    parts = []
    try:
        if state := _study_mode():
            parts.append(f"study mode is on{' for ' + state['subject'] if state.get('subject') else ''}")
        if c := _class_now(now):
            parts.append(f"{c['subject']} is scheduled until {c['end']}; attendance is unobserved")
        if d := _deadline_soon(now, 48):
            from services.proactive import deadlines
            parts.append(f"'{d['what']}' is due {deadlines.when(datetime.fromisoformat(d['due']), now)}")
        mins = _minutes_today(now)
        played, fun, studied = mins.get("gaming", 0), mins.get("entertainment", 0) + mins.get("social", 0), mins.get("study", 0)
        if played or fun:
            parts.append(f"today so far: {played} min gaming, {fun} min videos/social, {studied} min on study sites/apps")
    except Exception as e:
        logger.info(f"Personality context skipped: {e}")
    return ("Saved mode/schedule and recorded daily activity context (not proof of the current task): " + "; ".join(parts) + ".") \
        if parts else ""


# ── Quips on command replies ──────────────────────────────────────────────────

def _say(kind: str, **fields) -> str:
    return random.choice(QUIPS[kind]).format(**fields)


def _target(parsed: dict) -> tuple[str | None, str | None]:
    """(name, category) of what a command opened: an app or a site."""
    if name := parsed.get("app_name"):
        category = categorize("app", name.lower())
        if category not in DISTRACTING:  # "open instagram" / "open youtube": the site's category
            category = categorize("web", None, f"{name.lower().replace(' ', '')}.com") if category == "other" else category
        return name, category
    if url := parsed.get("url"):
        domain = urlparse(url if "//" in url else "//" + url).netloc or url
        return domain.removeprefix("www."), categorize("web", None, domain)
    return None, None


def _times_this_hour(parsed: dict, now: datetime) -> int:
    from services.activity.log import TARGET_KEYS, activity_log

    target = next((str(parsed[k]) for k in TARGET_KEYS if parsed.get(k)), None)
    if not target:
        return 0
    return len(activity_log.search("kind = 'command' AND action = ? AND target LIKE ? AND at >= ?",
                                   [parsed.get("action"), f"%{target}%", (now - timedelta(hours=1)).isoformat()]))


def _joke(kind: str, where: str, weight: float, **fields) -> str | None:
    """The line, if FRIDAY's learned sense of humour says a joke fits here (services/mind/humour.py)."""
    if not humour.should_joke(where, weight):
        return None
    humour.told(where, kind)  # the Boss's next message says whether it landed
    return _say(kind, **fields)


def quip(ran: list[tuple[dict, bool]], now: datetime) -> str | None:
    """A line to add after a command's reply, or None. How often is learned, per situation, from the Boss's reactions."""
    parsed, ok = ran[-1]
    if not ok:
        return None
    action = parsed.get("action")
    app, category = _target(parsed)
    if category in DISTRACTING:  # an obvious opening: counts more (weight), but still learned
        study, klass, deadline = _study_mode(), _class_now(now), _deadline_soon(now)
        if study:
            return _joke("study_mode", "study", OPENING, app=app, subject=f"{study['subject']} " if study.get("subject") else "")
        if klass:
            return _joke("class", "study", OPENING, app=app, subject=klass["subject"])
        if deadline:
            from services.proactive import deadlines
            return _joke("deadline", "deadline", OPENING, app=app, deadline=deadline["what"],
                         when=deadlines.when(datetime.fromisoformat(deadline["due"]), now))
        if (n := _times_this_hour(parsed, now)) >= REPEAT_LIMIT:
            return _joke("repeat", humour.situation(now), OPENING, app=app, n=n)
    if action == "end_mode" and parsed.get("routine") == "study" and parsed.get("minutes") is not None \
            and parsed["minutes"] < SHORT_STUDY:
        return _joke("short_study", "study", OPENING, minutes=max(1, parsed["minutes"]))
    if action == "start_mode" and parsed.get("routine") == "study":
        return _joke("start_study", "study", 1.5)
    if 1 <= now.hour < 5:
        return _joke("late", "late", 1.0, clock=now.strftime("%I:%M %p").lstrip("0"))
    if action in EVERYDAY:
        return _joke("everyday", humour.situation(now), 0.8)
    return None


def season(result, ran: list | None, now: datetime | None = None):
    """intent.try_system_action's reply with a quip added, when one fits."""
    if result is None or not ran or not result.success or not is_on():
        return result
    try:
        line = quip(ran, now or datetime.now())
    except Exception as e:  # a joke must never break a command
        logger.info(f"Quip skipped: {e}")
        return result
    return result._replace(message=f"{result.message} {line}") if line else result


# ── Proactive ─────────────────────────────────────────────────────────────────

def game_toast(app: str | None, now: datetime) -> str | None:
    """A game in front during study mode or a class: one toast per game and study session / class."""
    if not app or not is_on() or categorize("app", app) != "gaming":
        return None
    study, klass = _study_mode(), _class_now(now)
    if study:
        key, subject = f"{now.date()}:{study.get('since')}:{app}", f"{study['subject']} " if study.get("subject") else ""
    elif klass:
        key, subject = f"{now.date()}:{klass['start']}:{app}", f"{klass['subject']} class"
    else:
        return None
    if key in _toasted:
        return None
    _toasted.add(key)
    return _say("game_toast", app=app, subject=subject)


# ── Roast me ──────────────────────────────────────────────────────────────────

async def roast_me(provider_name: str, now: datetime | None = None, week: bool = False) -> str:
    """Today's (or the last 7 days') numbers, roasted by the chat AI (a plain version if no AI answers)."""
    from providers.base_provider import Message
    from providers.failover import complete_with_failover

    now = now or datetime.now()
    mins = _minutes_today(now, 7 if week else 1)
    span = "The last 7 days" if week else "Today so far"
    facts = (f"{span}: {mins.get('gaming', 0)} min gaming, {mins.get('entertainment', 0)} min videos, "
             f"{mins.get('social', 0)} min social media, {mins.get('study', 0)} min on study sites/apps, "
             f"{mins.get('coding', 0) + mins.get('project', 0)} min coding. It's {now:%I:%M %p}.")
    if d := _deadline_soon(now, 72):
        facts += f" '{d['what']}' is due {d['due']}."
    if config.AI_ASSIST_ONLY:
        from services.mind.wording import enhance
        return await enhance(f"{facts} Honestly? I've seen better time management from a screensaver.", provider_name)
    try:
        reply = await complete_with_failover(
            provider_name, [Message(role="user", content=facts)],
            PERSONA + f" Roast the user about their {'week' if week else 'day'} in 2 or 3 short sentences, using only these facts. "
            "Sarcastic, funny, not cruel. Plain text, no emoji.", 200)
        return reply.content.strip()
    except Exception as e:
        logger.info(f"Roast fell back to the plain version: {e}")
        return f"{facts} Honestly? I've seen better time management from a screensaver."
