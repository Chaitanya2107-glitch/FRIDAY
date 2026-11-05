"""
services/proactive/buttons.py

Buttons on FRIDAY's notifications, and what they learn:
  - habit suggestion (services/activity/habits.py) → Open it / Resume it / Save it, Not now, Stop suggesting;
    every suggestion and answer is saved there as training data
  - reminder → Snooze 10 min
  - session → "Start work mode?" Yes / No; a session summary → End mode (services/activity/sessions.py)
  - a new download → Move it / Leave it (services/files/filing.py)

How a click reaches FRIDAY: Windows can only open a link from a notification
button, so FRIDAY registers a friday:// link type for this user
(register_protocol). Clicking runs interfaces/protocol_handler.py, which posts
the token and answer to the local API (POST /api/v1/notify/respond).
Any web page could try to open a friday:// link too, so a click only counts
with the random one-time token of a notification FRIDAY actually showed, and
only with that notification's own answers. What to open comes from FRIDAY's
record of the notification, never from the link.
"""

import asyncio
import secrets
import sys
import time
import json
from urllib.parse import parse_qs, urlparse
from pathlib import Path

from core.config import config
from core.errors import FridayError
from core.logger import logger

PROTOCOL = "friday"
TOKEN_HOURS = 12        # a notification's buttons stop working after this
SNOOZE_MINUTES = 10
BUTTONS = {
    "task_followup": [("Review task", "review"), ("Not now", "pause"), ("Stop asking", "stop")],
    # habit suggestions (services/activity/habits.py): an app/site, a project, apps opened together
    "habit": [("Open it", "do"), ("Not now", "later"), ("Stop suggesting", "never")],
    "habit_project": [("Resume it", "do"), ("Not now", "later"), ("Stop suggesting", "never")],
    "habit_routine": [("Save it", "do"), ("Not now", "later"), ("Stop suggesting", "never")],
    "reminder": [(f"Snooze {SNOOZE_MINUTES} min", "snooze")],
    "mode": [("Yes", "start"), ("No", "no")],   # "Looks like you're working. Start work mode?"
    "mode_end": [("End mode", "end")],          # on a session summary while its mode is still on
    "file_move": [("Move it", "move"), ("Move & rename", "rename"), ("Leave it", "leave")],  # a download (filing.py)
    "attendance": [("Attended", "yes"), ("Missed", "no")],    # after a class (proactive/attendance.py)
    "join": [("Join", "join")],                               # a class warning with a saved Meet link (college.py)
    "explain": [("Explain", "explain")],                      # a failed terminal command (watch/done.py)
}
HANDLER = Path(__file__).resolve().parents[2] / "interfaces" / "protocol_handler.py"

_offers: dict[str, dict] = {}  # token → {"kind", "at", …what the notification was about}


def bind_decision(offered, event_id):
    for _, link in offered or []:
        token = parse_qs(urlparse(link).query).get("token", [None])[0]
        if token in _offers:
            _offers[token]["decision_id"] = event_id


def offer(kind: str, **about) -> list[tuple[str, str]]:
    """Remember a notification about to be shown; returns its buttons as (label, friday:// link)."""
    now = time.time()
    for token in [t for t, o in _offers.items() if now - o["at"] > TOKEN_HOURS * 3600]:
        del _offers[token]
    token = secrets.token_urlsafe(16)
    _offers[token] = {"kind": kind, "at": now, **about}
    return [(label, f"{PROTOCOL}://{kind}?token={token}&answer={answer}") for label, answer in BUTTONS[kind]]


def respond(token: str, answer: str) -> str:
    """A button was clicked. Raises FridayError for an unknown/expired token or an answer that notification hasn't."""
    about = _offers.get(token)
    if about is None or time.time() - about["at"] > TOKEN_HOURS * 3600:
        raise FridayError("That notification has expired.", status_code=404)
    if answer not in {a for _, a in BUTTONS[about["kind"]]}:
        raise FridayError("That button isn't on this notification.", status_code=400)
    del _offers[token]  # each notification answers once
    from services.mind.cognition import cognition
    cognition.record("reaction", "notification", json.dumps({"kind": about["kind"], "answer": answer,
                     "decision_id": about.get("decision_id")}), public=True)
    logger.info(f"Notification button: {about['kind']} → {answer}")

    if about["kind"] == "reminder":
        from services.reminders.service import reminders
        return reminders.snooze(about["text"], SNOOZE_MINUTES)

    if about["kind"] in ("mode", "mode_end"):
        return _mode_answer(about, answer)

    if about["kind"] == "explain":
        return _explain(about["command"])

    if about["kind"] == "join":
        from services.automation.system_control import system
        system.open_url(about["url"])
        return "Joining."

    if about["kind"] == "attendance":
        from services.proactive import attendance
        return attendance.answer(about, answer)

    if about["kind"] == "task_followup":
        from datetime import datetime
        from services.mind import task_followups
        try:
            return task_followups.respond(about["followup"], answer, datetime.now())
        except ValueError as error:
            raise FridayError(str(error)) from error

    if about["kind"] == "file_move":
        if answer == "leave":
            return "Okay, left it in Downloads."
        from services.files import filing
        try:
            return filing.move(about["path"], about["folder"], rename=answer == "rename")
        except (FridayError, OSError) as e:
            raise FridayError(f"Couldn't move it: {getattr(e, 'message', e)}") from None

    from services.activity import habits  # habit, habit_project, habit_routine
    try:
        return habits.answer(about, answer)
    except FridayError:
        raise
    except Exception as e:  # opening / resuming / saving failed: say so on the button's reply
        raise FridayError(f"Couldn't do that: {e}") from None


def _explain(command: str) -> str:
    """[Explain] on a failed command: the vision AI reads the terminal on screen; the answer comes as a notification."""
    from services.reminders.service import show_toast
    from services.vision.screen import ask_about_screen

    question = (f"The terminal on screen ran `{command}` and it failed. In 2-3 short sentences: what went wrong and "
                "how to fix it. If no terminal output is visible, say so.")
    try:
        reply = asyncio.run(ask_about_screen(question, [], config.ACTIVE_PROVIDER, 300)).content.strip()
    except Exception as e:  # free vision models are often busy
        reply = f"I couldn't read the screen for that: {getattr(e, 'message', e)}"
    show_toast("F.R.I.D.A.Y", reply[:400])
    return reply


def _mode_answer(about: dict, answer: str) -> str:
    """A session notification's button (runs in a worker thread; starting a mode needs FRIDAY's event loop)."""
    from services.automation import intent

    name = about["mode"]
    if about["kind"] == "mode_end":
        return intent._end_mode(name).message
    from services.activity.log import activity_log
    activity_log.log_feedback(f"mode:{name}", answer)  # learning data, like the habit answers
    if answer == "no":
        from services.proactive import watcher
        watcher.decline_session(name)
        return f"Okay, no more {name} mode suggestions today."
    started = asyncio.run_coroutine_threadsafe(
        intent._start_mode(name, config.ACTIVE_PROVIDER, about.get("subject", "")), about["loop"])
    return started.result(timeout=120).message


def register_protocol() -> None:
    """Point friday:// links at interfaces/protocol_handler.py (for this user only; no admin needed)."""
    import winreg

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    command = f'"{pythonw if pythonw.exists() else sys.executable}" "{HANDLER}" "%1" {config.API_PORT}'
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:F.R.I.D.A.Y notification button")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}\shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    except OSError as e:
        logger.warning(f"Couldn't register friday:// for notification buttons: {e}")
