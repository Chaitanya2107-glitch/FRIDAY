"""
services/automation/modes.py

Modes (profiles): "start study mode" / "switch to gaming mode" … "end study mode".
Unlike a routine, a mode stays on until it's ended:
  - starting it runs its steps (normal FRIDAY commands: open apps, set the volume,
    play music …) through intent.py, like a routine
  - while a "quiet" mode is on, FRIDAY holds nudges and doesn't speak on its own
    (the same as gaming/fullscreen — services/proactive/watcher.py is_busy)
  - ending it closes the apps its steps opened and puts the volume back
Only one mode is on at a time; starting another ends the current one first.
A mode left on is caught (DOESNT_FIT, left_on): 15 min on apps that don't fit it → a reminder;
45 min, or an hour away from the laptop → it ends itself.

Kept in memory/modes.json (editable by hand); the defaults are made on first use:
    {"study": {"steps": ["set volume to 30"], "quiet": true}, …}
  "when I start study mode, open vs code, play lofi and set volume to 20"  → its steps
  "make study mode quiet" / "make study mode not quiet"
  "what mode am I in", "list my modes", "delete study mode"
  "start study mode for DBMS"  → until it ends, the time counts as studying DBMS
"""

import json
import re
import time

from core.config import config
from core.logger import logger
from services import settings_store
from services.automation.command_words import split_steps
from services.automation.routines import _base_verb
from services.automation.system_control import AutomationError

path = config.MEMORY_DIR / "modes.json"  # tests point this elsewhere
state_path = config.MEMORY_DIR / "mode_state.json"
MODE_ACTIONS = {"mode_status", "list_modes", "set_mode_steps", "set_mode_quiet", "delete_mode"}  # start/end: intent.py
DEFAULT_MODES = {
    "study": {"steps": ["set volume to 30"], "quiet": True},
    "work": {"steps": [], "quiet": True},
    "gaming": {"steps": [], "quiet": True},
    "chill": {"steps": ["play music"], "quiet": False},
}

# A mode left on (services/proactive/watcher.py): the kinds of app (services/activity/categories.py) that don't
# fit it — everything else is neutral. Modes not listed here (chill, your own) only end when you've been away.
DOESNT_FIT = {
    "work": {"entertainment", "social", "gaming"},
    "study": {"entertainment", "social", "gaming"},
    "gaming": {"coding", "documents", "study"},
}
REMIND_AFTER_MINUTES = 15   # on apps that don't fit: "Work mode's still on …" [End mode]
END_AFTER_MINUTES = 45      # … this long: the mode ends itself
AWAY_ENDS_AFTER_MINUTES = 60

_NAME = r"(?P<name>[a-z][\w -]{0,30}?)"
_START = re.compile(rf"^(?:start|switch to|go (?:into|to)|enter|turn on|activate|begin|put me in)\s+(?:the\s+|my\s+)?{_NAME}\s+mode"
                    rf"(?:\s+for\s+(?P<subject>.+))?$"
                    rf"|^{_NAME.replace('name', 'name2')}\s+mode\s+on$", re.I)
_END = re.compile(rf"^(?:end|stop|exit|leave|quit|turn off|deactivate|finish)\s+(?:the\s+|my\s+)?(?:{_NAME}\s+)?mode$"
                  rf"|^{_NAME.replace('name', 'name2')}\s+mode\s+off$|^(?:normal mode|back to normal)$", re.I)
_STATUS = re.compile(r"^(?:what|which) mode (?:am i in|is on|are you in)$|^(?:current|my) mode$", re.I)
_NAMED_STATUS = re.compile(rf"^(?:is (?:the |my )?{_NAME} mode (?:on|off|active|enabled)|"
                           rf"{_NAME.replace('name', 'name2')} mode status)$", re.I)
_LIST = re.compile(r"^(?:(?:list|show)(?: me)?(?: all)?(?: my| the)? modes|what modes do i have|my modes)$", re.I)
_SET = re.compile(rf"^(?:when(?:ever)? i (?:start|switch to|turn on|enter)|(?:set|change) (?:the )?steps (?:for|of))\s+"
                  rf"(?:the\s+|my\s+)?{_NAME}\s+mode[\s,:]+(?P<steps>.+)$", re.I)
_QUIET = re.compile(rf"^make\s+(?:the\s+|my\s+)?{_NAME}\s+mode\s+(?P<not>not\s+|un)?quiet$", re.I)
_DELETE = re.compile(rf"^(?:delete|remove|forget)\s+(?:the\s+|my\s+)?{_NAME}\s+mode$", re.I)
_STEP_LEAD = re.compile(r"^[\s,:;-]*(?:(?:you should|please|then|to|just|i want you to)\s+)*", re.I)
_OPEN_STEP = re.compile(r"^(?:open|launch|start|run)\s+(?P<app>.+)$", re.I)


# ── Files ─────────────────────────────────────────────────────────────────────

def load() -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {name: dict(mode) for name, mode in DEFAULT_MODES.items()}
    except (OSError, ValueError) as e:
        raise AutomationError(f"I couldn't read {path} — is there a typo in it? ({e})") from e
    return {str(n).strip().lower(): {"steps": [str(s) for s in m.get("steps", [])], "quiet": bool(m.get("quiet"))}
            for n, m in data.items() if isinstance(m, dict)}


def _save(modes: dict[str, dict]) -> None:
    settings_store.save(path, modes)


def active(*, strict: bool = False) -> dict | None:
    """The mode that's on: {"name", "opened": [apps], "volume": level before, "quiet"} or None."""
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) or None
        if state is not None and (not isinstance(state, dict) or not isinstance(state.get("name"), str)):
            raise ValueError("Invalid mode state")
        return state
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        if strict:
            raise AutomationError("Current mode status is unavailable.")
        return None


def _set_active(state: dict | None) -> None:
    settings_store.save(state_path, state or {})


def is_quiet_mode() -> bool:
    """A quiet mode is on: nudges are held and FRIDAY doesn't speak on its own."""
    state = active()
    return bool(state and state.get("quiet"))


# ── Matching ──────────────────────────────────────────────────────────────────

def match_mode_command(text: str) -> dict | None:
    """Mode commands. `text` has been through normalize_command()."""
    text = text.strip()
    if m := _SET.match(text):
        steps = [_base_verb(_STEP_LEAD.sub("", s).strip(" .")) for s in split_steps(m["steps"])]
        return {"type": "system", "action": "set_mode_steps", "mode": m["name"].strip().lower(), "steps": [s for s in steps if s]}
    if m := _QUIET.match(text):
        return {"type": "system", "action": "set_mode_quiet", "mode": m["name"].strip().lower(), "quiet": not m["not"]}
    if _STATUS.match(text):
        return {"type": "system", "action": "mode_status"}
    if m := _NAMED_STATUS.fullmatch(text):
        return {"type": "system", "action": "mode_status", "mode": (m['name'] or m['name2']).strip().lower()}
    if _LIST.match(text):
        return {"type": "system", "action": "list_modes"}
    if m := _DELETE.match(text):
        return {"type": "system", "action": "delete_mode", "mode": m["name"].strip().lower()}
    if m := _END.match(text):
        return {"type": "system", "action": "end_mode", "mode": (m["name"] or m["name2"] or "").strip().lower()}
    if m := _START.match(text):
        name = (m["name"] or m["name2"]).strip().lower()
        try:
            known = name in load()
        except AutomationError:
            known = False
        return {"type": "system", "action": "start_mode", "mode": name,
                "subject": (m["subject"] or "").strip(" .")} if known else None
    return None


# ── Starting and ending (the steps themselves run in intent.py) ───────────────

@settings_store.synchronized
def begin(name: str, volume_now: int | None, subject: str = "") -> tuple[dict, list[str]]:
    """Record the mode as on ("… for DBMS": its time counts as studying that subject,
    services/activity/study.py); returns (its settings, its steps to run)."""
    mode = load().get(name)
    if mode is None:
        raise AutomationError(f'You don\'t have a "{name}" mode. Say "list my modes".')
    opened = [m["app"].strip() for s in mode["steps"] if (m := _OPEN_STEP.match(s.strip()))]
    if subject:
        from services.proactive.timetable import subject_named  # avoid an import cycle
        subject = subject_named(subject)
    _set_active({"name": name, "opened": opened, "volume": volume_now, "quiet": mode["quiet"], "subject": subject,
                 "since": time.time()})
    logger.info(f"Mode on: {name}" + (f" for {subject}" if subject else ""))
    return mode, mode["steps"]


@settings_store.synchronized
def finish() -> dict | None:
    """Mark no mode as on; returns what was on (to undo it), or None."""
    state = active()
    _set_active(None)
    if state:
        logger.info(f"Mode off: {state['name']}")
    return state


def left_on(name: str, off_minutes: float, idle_minutes: float) -> str | None:
    """A mode that may have been forgotten: "end", "remind", or None. off_minutes = how long the
    apps in use haven't fitted it (DOESNT_FIT); idle_minutes = how long nobody has touched the laptop."""
    if idle_minutes >= AWAY_ENDS_AFTER_MINUTES or (name in DOESNT_FIT and off_minutes >= END_AFTER_MINUTES):
        return "end"
    if name in DOESNT_FIT and off_minutes >= REMIND_AFTER_MINUTES:
        return "remind"
    return None


@settings_store.synchronized
def run(parsed: dict) -> str:
    action, modes = parsed["action"], load()
    if action == "mode_status":
        state = active(strict=True)
        if requested := parsed.get('mode'):
            if state and state['name'] == requested:
                return f"{requested.title()} mode is on."
            current = state['name'].title() if state else 'Normal'
            return f"{requested.title()} mode is off. Current mode: {current}."
        if not state:
            return "Normal mode is active."
        return f"You're in {state['name']} mode" + (f" for {state['subject']}." if state.get("subject") else ".")
    if action == "list_modes":
        return "Your modes: " + "; ".join(
            f"{n}{' (quiet)' if m['quiet'] else ''}: {', '.join(m['steps']) or 'no steps'}" for n, m in modes.items()) + "."
    name = parsed["mode"]
    if action == "delete_mode":
        if name not in modes:
            raise AutomationError(f'You don\'t have a "{name}" mode.')
        del modes[name]
        _save(modes)
        return f"Deleted {name} mode."
    mode = modes.setdefault(name, {"steps": [], "quiet": False})
    if action == "set_mode_quiet":
        mode["quiet"] = parsed["quiet"]
        _save(modes)
        return f"{name.title()} mode is now {'quiet: nudges wait and I stay silent' if mode['quiet'] else 'not quiet'}."
    if not parsed["steps"]:
        raise AutomationError(f'Tell me the steps too, like "when I start {name} mode, open vs code and play lofi".')
    mode["steps"] = parsed["steps"]
    _save(modes)
    numbered = ", ".join(f"{i}. {s}" for i, s in enumerate(parsed["steps"], 1))
    return f'Done. "start {name} mode" will now: {numbered}.'
