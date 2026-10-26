"""
services/proactive/watcher.py

FRIDAY speaking up without being asked — as notifications (out loud only with "free will" on,
services/mind/talk.py). Once a minute:
  - the morning briefing (briefing.py), the first time the user is at the
    laptop each day after BRIEFING_AFTER_HOUR
  - nudges (nudges.py) and class warnings (timetable.py)
  - habit suggestions (services/activity/habits.py), while the user is active and not busy (their feedback,
    not fixed quiet hours, decides what's welcome late at night)
  - the evening git notification (GIT_REMINDER_HOUR, git_status.py)
  - sessions (services/activity/sessions.py): "Start work mode?" once a work stretch
    reaches 10 min, and a summary when a session of 20+ min ends
  - the daily journal (JOURNAL_HOUR) and, on Sundays, the weekly summary (weekly.py)
  - a chat gone quiet is summed up for long-term memory (services/memory/episodes.py)
  - a mode left on (modes.py left_on): a reminder once the apps in use stop fitting it, and it
    ends itself when that lasts or the user has been away
While the user is gaming or anything is fullscreen (is_busy), nudges are held
and shown afterwards, and the briefing and git notification wait (reminders
check is_busy too before speaking). Only a battery about to die still shows.

Commands: "brief me", "pause nudges for an hour", "turn off nudges", "turn on nudges".
The last briefing date and the nudge switches are kept in memory/proactive.json,
so a restart doesn't repeat the briefing or turn nudges back on.
"""

import asyncio
import ctypes
import json
import re
import time
from datetime import datetime

from core.config import config
from core.logger import logger
from services.activity import git_status, habits, journal, limits, sessions, weekly
from services.activity.categories import categorize
from services.activity.log import activity_log, idle_seconds
from services.automation import personality
from services.automation.system_control import AutomationError
from services.proactive import attendance, briefing, buttons, college, deadlines, timetable
from services.proactive.nudges import Nudger, read_system
from services.mind.training import show_toast
from services.mind import notifications

CHECK_SECONDS = 60
ACTIVE_WITHIN_SECONDS = 60  # "at the laptop" = used mouse/keyboard within this
TITLE = "F.R.I.D.A.Y"
state_path = config.MEMORY_DIR / "proactive.json"  # tests point this elsewhere

PROACTIVE_ACTIONS = {"briefing", "pause_nudges", "nudges_off", "nudges_on", "eye_breaks"}
_BRIEFING = re.compile(
    r"^(?:brief me|(?:give me |what's |what is |read me )?(?:my |the |today's )?(?:morning |daily )?briefing)$", re.I
)
_PAUSE = re.compile(
    r"^(?:pause|mute|snooze|silence|hold)\s+(?:the\s+|my\s+|your\s+)?nudges"
    r"(?:\s+for\s+(?:(?P<n>\d+)|an?|one)\s*(?P<unit>minutes?|mins?|hours?|hrs?))?$", re.I,
)
_OFF = re.compile(r"^(?:turn off|disable|stop)\s+(?:the\s+|my\s+|all\s+|your\s+)?nudges$", re.I)
_ON = re.compile(r"^(?:turn on|enable|resume|unpause)\s+(?:the\s+|my\s+|your\s+)?nudges$", re.I)
_EYES = re.compile(r"^(?:(?:turn|switch) (?P<a>on|off)|(?P<b>start|stop|enable|disable)) (?:the |my )?eye breaks?"
                   r"(?: reminders?)?$", re.I)

_nudger = Nudger()
_held: list = []  # nudges waiting until the user stops gaming / leaves fullscreen


# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(**changes) -> None:
    state = load_state() | changes
    try:
        state_path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as e:
        logger.warning(f"Couldn't save {state_path.name}: {e}")


def nudges_active(now_ts: float | None = None) -> bool:
    state = load_state()
    return config.NUDGES_ENABLED and not state.get("nudges_off") and (now_ts or time.time()) >= state.get("paused_until", 0)


QUNS_BUSY, QUNS_FULLSCREEN_GAME, QUNS_PRESENTATION = 2, 3, 4  # SHQueryUserNotificationState answers


def is_busy() -> bool:
    """
    Gaming, or anything fullscreen (a game, a video, a presentation): FRIDAY holds nudges and doesn't speak
    on its own. Answers to the user's own commands are still spoken. A quiet mode ("start study mode") counts too.
    """
    from services.automation import modes  # avoid an import cycle at startup

    return modes.is_quiet_mode() or fullscreen_or_gaming()


def fullscreen_or_gaming() -> bool:
    state = ctypes.c_int()
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0 \
                and state.value in (QUNS_BUSY, QUNS_FULLSCREEN_GAME, QUNS_PRESENTATION):
            return True
    except (AttributeError, OSError):
        pass
    return bool(activity_log.app) and categorize("app", activity_log.app) == "gaming"


# ── The loop ──────────────────────────────────────────────────────────────────

def decline_session(group: str) -> None:
    """ "No" on "Start work mode?": no more suggestions for that kind of session today."""
    offers = load_state().get("session_offers", {})
    offers[group] = {"day": datetime.now().date().isoformat()} | offers.get(group, {}) | {"declined": True}
    _save_state(session_offers=offers)


async def _check_sessions(now: datetime) -> None:
    """Offer the mode for a running session; sum a session up once it's over."""
    from services.automation import modes  # avoid an import cycle at startup

    found = await asyncio.to_thread(sessions.recent, activity_log, now)
    try:
        names = set(modes.load())
    except AutomationError:
        names = set()
    on, state = modes.active(), load_state()
    offers = state.get("session_offers", {})
    if not on and (s := sessions.to_suggest(found, offers, names, now)):
        offers[s.group] = {"day": now.date().isoformat(), "at": now.timestamp()}
        _save_state(session_offers=offers)  # first, so a failure can't repeat it every minute
        activity_log.log_feedback(f"mode:{s.group}", "suggested")
        await _notify(f"Looks like you're {sessions.DOING[s.group]}. Start {s.group} mode?",
                      buttons.offer("mode", mode=s.group, loop=asyncio.get_running_loop()))
    summed = state.get("sessions_summed", [])
    for s in sessions.just_ended(found, now):
        if sessions.key(s) in summed:
            continue
        summed = (summed + [sessions.key(s)])[-20:]
        _save_state(sessions_summed=summed)
        text = sessions.summary(s, await asyncio.to_thread(sessions.commits_in, s))
        mode_on = on and on.get("name") == s.group
        await _notify(text, buttons.offer("mode_end", mode=s.group) if mode_on else None)


async def _deliver(text: str, *, urgent=False) -> None:
    await _notify(text, urgent=urgent)


async def _notify(text, offered_buttons=None, *, kind="nudge", subject="", urgent=False):
    return await notifications.notify(text, offered_buttons, kind=kind, subject=subject, transport=show_toast, urgent=urgent)


async def _suggest_habit(now: datetime) -> None:
    """A habit suggestion, with its buttons (services/activity/habits.py decides whether it's the moment)."""
    s = await asyncio.to_thread(habits.next_suggestion, activity_log, now)
    if s:
        await _notify(s.text, buttons.offer(
            s.buttons, habit=s.key, id=s.id, minute=s.minute, loop=asyncio.get_running_loop()))


_off_mode_since: float | None = None  # when the apps in use stopped fitting the mode that's on
_reminded_mode: float | None = None   # the "since" of the mode already reminded about (once per mode)
DOING = {"entertainment": "videos", "social": "social media", "gaming": "games", "coding": "code",
         "documents": "documents", "study": "study stuff"}


async def _check_mode_left_on(now: datetime) -> None:
    """A mode left on: remind once when the apps in use don't fit it, end it when that lasts, or when you're away."""
    global _off_mode_since, _reminded_mode
    from services.automation import intent, modes  # avoid an import cycle at startup

    on = modes.active()
    category = categorize("app", activity_log.app, title=activity_log.title) if activity_log.app else None
    if not on or category not in modes.DOESNT_FIT.get(on["name"], ()):
        _off_mode_since = None
    elif _off_mode_since is None:
        _off_mode_since = now.timestamp()
    if not on:
        return
    off_minutes = (now.timestamp() - _off_mode_since) / 60 if _off_mode_since else 0.0
    what = on["name"].title()
    act = modes.left_on(on["name"], off_minutes, idle_seconds() / 60)
    if act == "end":
        _off_mode_since = None
        ended = await asyncio.to_thread(intent._end_mode, on["name"])
        why = f"you'd moved on to {DOING.get(category, category)}" if off_minutes else "you'd stepped away"
        await _notify(f"Ended {on['name']} mode — {why}. {ended.message}", kind='status')
    elif act == "remind" and _reminded_mode != on.get("since"):
        _reminded_mode = on.get("since")
        await _notify(f"{what} mode's still on, but you've been on "
                      f"{DOING.get(category, category)} for {round(off_minutes)} min — done with it?",
                      buttons.offer("mode_end", mode=on["name"]))


async def tick(now: datetime | None = None) -> None:
    now = now or datetime.now()
    from services.mind import reasoning
    await reasoning.review(now)
    with notifications.collect(now) as batch:
        await _tick(now)
        if nudges_active(now.timestamp()) and not await asyncio.to_thread(is_busy) and idle_seconds() < ACTIVE_WITHIN_SECONDS:
            if proposal := await asyncio.to_thread(reasoning.suggestion, now):
                await _notify(proposal["text"], kind="reasoning", subject=f"reasoning:{proposal['id']}")
    await notifications.dispatch(batch)


async def _tick(now: datetime) -> None:
    now = now or datetime.now()
    await _check_mode_left_on(now)  # first: a forgotten quiet mode shouldn't keep her quiet this minute
    busy = await asyncio.to_thread(is_busy)
    if roast := personality.game_toast(activity_log.app, now):  # a game in study mode / class — shown while gaming too
        await _deliver(roast)
        from services import body_state
        body_state.push("roast", roast)  # her body side-eyes you
    for alert in await asyncio.to_thread(limits.due_alerts, activity_log, now):  # app limits — shown while gaming too
        await _deliver(alert)
    for warning in timetable.due_warnings(now):  # "DBMS starts in 10 minutes in room 204." — shown even while busy
        if link := college.link_for(warning.split(" starts in ")[0]):  # a Meet link saved for the subject: [Join]
            await _notify(warning, buttons.offer("join", url=link), kind="class_warning",
                          subject=warning.split(" starts in ")[0])
        else:
            await _notify(warning, kind="class_warning", subject=warning.split(" starts in ")[0])
    from services.automation import modes  # avoid an import cycle at startup
    offer = college.class_start_offer(now, idle_seconds() < ACTIVE_WITHIN_SECONDS, bool(modes.active()))
    if offer:  # "DBMS has started. Start study mode for DBMS?" [Yes] [No]
        await _notify(offer["text"], buttons.offer(
            "mode", mode="study", subject=offer["subject"], loop=asyncio.get_running_loop()),
            kind="class_mode", subject=offer["subject"])
    for alert in deadlines.due_alerts(now):  # "DBMS assignment is due tomorrow at 11:59 PM (in 24 hours)." — same
        await _deliver(alert)
    for ask in attendance.due_asks(now):  # "DBMS (9:30–10:30 AM): attended?" [Attended] [Missed] — same
        await _notify(ask["text"], buttons.offer(
            "attendance", date=ask["date"], subject=ask["subject"], start=ask["start"],
            session_revision=ask.get("session_revision")),
            kind="attendance", subject=ask["subject"])
    from services.telegram import summaries as telegram_summaries
    if config.LEARNING_DATA_ENABLED:
        from services.learning import service as learning_service
        try:
            await asyncio.to_thread(learning_service.refresh, activity_log, now)
        except Exception as error:
            logger.warning("Learning-data refresh unavailable: %s", type(error).__name__)
    await telegram_summaries.tick(now)  # daily + nightly + weekly, even while busy or at the laptop
    if not busy:
        while _held:  # what waited while the user was gaming / fullscreen
            await _deliver(_held.pop(0).text)
    if (
        not busy  # the briefing and the git reminder wait until the game / video is over
        and config.BRIEFING_ENABLED
        and load_state().get("last_briefing") != now.date().isoformat()
        and now.hour >= config.BRIEFING_AFTER_HOUR
        and idle_seconds() < ACTIVE_WITHIN_SECONDS
    ):
        _save_state(last_briefing=now.date().isoformat())  # first, so a failure can't repeat it every minute
        logger.info("Morning briefing")
        await _deliver(await asyncio.to_thread(briefing.build, now))

    if (
        not busy
        and config.GIT_REMINDER_HOUR.strip().isdigit()
        and now.hour >= int(config.GIT_REMINDER_HOUR)
        and load_state().get("last_git_reminder") != now.date().isoformat()
        and nudges_active(now.timestamp())
    ):
        _save_state(last_git_reminder=now.date().isoformat())  # first, so a failure can't repeat it every minute
        summary = await asyncio.to_thread(git_status.uncommitted_summary)
        if summary:
            await _deliver(summary)

    if (
        not busy
        and config.JOURNAL_HOUR.strip().isdigit()
        and now.hour >= int(config.JOURNAL_HOUR)
        and load_state().get("last_journal") != now.date().isoformat()
    ):
        _save_state(last_journal=now.date().isoformat())  # first, so a failure can't repeat it every minute
        note = await asyncio.to_thread(journal.evening_note, now.date(), activity_log)
        if note:
            await _deliver(note)
        from services.activity import insights  # the night's training data: every command, with features
        await asyncio.to_thread(insights.write_command_dataset, activity_log)
        from services.mind import humour, learner, reflection  # FRIDAY thinks over the day and updates what it knows
        await asyncio.to_thread(humour.fade)
        from services.mind import talk
        await asyncio.to_thread(talk.fade)
        from services.mind import brain, life
        await asyncio.to_thread(life.close_day, now)  # her own diary
        await asyncio.to_thread(brain.nightly, now)   # old thoughts and passing topics are forgotten
        from services.memory.semantic import semantic_memory
        await asyncio.to_thread(semantic_memory.fade, now)  # unused guesses about the Boss weaken, weak ones go
        await reflection.reflect(activity_log, now.date())
        try:
            await asyncio.to_thread(learner.train, activity_log, now)  # retrain; the model leads only while it wins
        except Exception as e:
            logger.warning(f"Nightly training failed: {e}")
        if now.weekday() == 6:  # Sunday: the weekly summary too
            monday = weekly.monday_of(now.date())
            note = await asyncio.to_thread(weekly.note, monday, activity_log)
            if note:
                await asyncio.to_thread(weekly.write, monday, activity_log)
                await _deliver(note)
            from services.memory import semantic  # what FRIDAY guessed about you this week, to check
            if review := await asyncio.to_thread(semantic.weekly_review, now):
                await _deliver(review)

    if not busy:
        await _check_sessions(now)

    if nudges_active(now.timestamp()):
        readings = await asyncio.to_thread(read_system)
        notifications.observe(readings)
        for nudge in _nudger.check(readings, now, bool(load_state().get("eye_breaks"))):
            if busy and not nudge.urgent:
                if nudge.keep:
                    _held.append(nudge)  # shown when the game / fullscreen app is closed
                continue
            await _deliver(nudge.text, urgent=nudge.urgent)  # urgent warnings bypass learned delivery preferences
        if not busy and idle_seconds() < ACTIVE_WITHIN_SECONDS:  # late nights too: habits learn from "Not now"
            await _suggest_habit(now)

    from services.mind import brain, reflection, talk, task_followups
    try:  # her brain, once a minute: what only shows with time, and one lookup of something she can't place
        await asyncio.to_thread(brain.think, activity_log, now, busy)
        if not busy:
            await brain.learn_something(activity_log, now)
    except Exception as e:
        logger.warning(f"Brain tick failed: {e}")
    # FRIDAY speaking on her own, when she's learned it's welcome
    followup = await task_followups.tick(now, busy, idle_seconds())
    waiting = followup or await asyncio.to_thread(task_followups.pending_conversation)
    if not waiting and (said := await talk.tick(activity_log, now, busy, idle_seconds())):  # late nights are learned, not blocked
        await talk.deliver(said)  # spoken AND a notification (for when the laptop is muted)
    if not busy:
        await reflection.reflect_if_due(activity_log, now)  # rethink what she knows every few hours
        from services.memory import episodes
        await episodes.summarize_if_due()  # a chat that's gone quiet: remembered as a conversation


async def run_proactive() -> None:
    """Runs for the lifetime of the API process; started from app.py's lifespan."""
    logger.info("Briefing and nudges started")
    while True:
        try:
            await tick()
        except Exception as e:
            logger.error(f"Briefing/nudge check failed: {e}", exc_info=True)
        await asyncio.sleep(CHECK_SECONDS)


# ── Commands ──────────────────────────────────────────────────────────────────

def match_proactive_command(text: str) -> dict | None:
    """`text` has already been through normalize_command()."""
    text = text.strip()
    if _BRIEFING.match(text):
        return {"type": "system", "action": "briefing"}
    paused = _PAUSE.match(text)
    if paused:
        amount = int(paused["n"] or 1)
        minutes = amount * (60 if (paused["unit"] or "hour").startswith("h") else 1)
        return {"type": "system", "action": "pause_nudges", "minutes": minutes}
    if _OFF.match(text):
        return {"type": "system", "action": "nudges_off"}
    if _ON.match(text):
        return {"type": "system", "action": "nudges_on"}
    if m := _EYES.match(text):
        return {"type": "system", "action": "eye_breaks", "on": (m["a"] or m["b"]).lower() in ("on", "start", "enable")}
    return None


def run_proactive_command(parsed: dict) -> str:
    """Blocking (the briefing reads the weather) — run it in a thread."""
    action = parsed["action"]
    if action == "briefing":
        _save_state(last_briefing=datetime.now().date().isoformat())  # asked for it: no automatic one today
        return briefing.build()
    if action == "pause_nudges":
        minutes = int(parsed["minutes"])
        _save_state(paused_until=time.time() + minutes * 60)
        span = f"{minutes // 60} hour{'s' if minutes >= 120 else ''}" if minutes % 60 == 0 else f"{minutes} minutes"
        return f"Okay, no nudges for {span}."
    if action == "eye_breaks":
        _save_state(eye_breaks=bool(parsed["on"]))
        return ("Eye breaks on: every 20 minutes at the screen, a nudge to look away for 20 seconds."
                if parsed["on"] else "Eye breaks off.")
    if action == "nudges_off":
        _save_state(nudges_off=True)
        return 'Nudges are off. Say "turn on nudges" to get them back.'
    _save_state(nudges_off=False, paused_until=0)
    return "Nudges are back on."
