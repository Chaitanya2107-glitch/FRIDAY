"""
services/activity/limits.py

Daily time limits per app: "limit valorant to 2 hours a day", "remove the limit on valorant",
"what are my app limits". Kept in memory/app_limits.json ({"valorant": 120}, minutes).

Time counts while the app is in front (the activity log); a name matches any app containing
it ("valorant" → valorant-win64-shipping). While a limited app is in front the proactive watcher
shows a toast WARN_MINUTES before the limit, at it, and every OVER_EVERY_MINUTES after —
once each per day. Nothing is closed.
"""

import json
import re
from datetime import datetime

from core.config import config
from services.automation.system_control import AutomationError

LIMIT_ACTIONS = {"set_limit", "remove_limit", "list_limits"}
path = config.MEMORY_DIR / "app_limits.json"  # tests point this elsewhere
WARN_MINUTES = 10
OVER_EVERY_MINUTES = 30

_UNIT = r"(?P<n>\d+(?:\.\d+)?) ?(?P<unit>h|hrs?|hours?|m|mins?|minutes?)"
_SETS = (re.compile(rf"^(?:limit|cap) (?P<app>.+?) to {_UNIT}(?: (?:a|per|each) day| daily)?$", re.I),
         re.compile(rf"^set (?:a |an )?(?:daily )?(?:time )?limit of {_UNIT}(?: (?:a|per) day)? (?:for|on) (?P<app>.+)$", re.I))
_REMOVE = re.compile(r"^(?:remove|delete|clear|drop|lift|cancel)(?: the| my)? (?:daily )?(?:time )?limit (?:on|for) (?P<app>.+)$"
                     r"|^no (?:more )?limit (?:on|for) (?P<app2>.+)$", re.I)
_LIST = re.compile(r"^(?:(?:list|show|what are)(?: me)? (?:my |the )?(?:app |daily |time )*limits|my (?:app )?limits)$", re.I)

_told: set[tuple[str, str, int]] = set()  # (app, day, minute mark) already shown


def match_limit_command(text: str) -> dict | None:
    text = text.strip().rstrip(".!?")
    if m := next(filter(None, (p.match(text) for p in _SETS)), None):
        minutes = float(m["n"]) * (60 if m["unit"].lower().startswith("h") else 1)
        return {"type": "system", "action": "set_limit", "app": _name(m["app"]), "minutes": round(minutes)}
    if m := _REMOVE.match(text):
        return {"type": "system", "action": "remove_limit", "app": _name(m["app"] or m["app2"])}
    if _LIST.match(text):
        return {"type": "system", "action": "list_limits"}
    return None


def _name(app: str) -> str:
    return re.sub(r"^(?:the |my )|(?:\.exe)$", "", app.strip().lower()).strip()


def load() -> dict[str, int]:
    try:
        return {str(k): int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _save(limits: dict[str, int]) -> None:
    path.write_text(json.dumps(limits, indent=2), encoding="utf-8")


def _duration(minutes: float) -> str:
    minutes = int(minutes)
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest}m" if hours and rest else f"{hours}h" if hours else f"{rest}m"


def run(parsed: dict) -> str:
    limits = load()
    action = parsed["action"]
    if action == "list_limits":
        return "Daily limits: " + ", ".join(f"{a} {_duration(m)}" for a, m in limits.items()) + "." if limits \
            else 'No app limits. Try "limit valorant to 2 hours a day".'
    app = parsed["app"]
    if action == "remove_limit":
        if app not in limits:
            raise AutomationError(f"There's no limit on {app}.")
        del limits[app]
        _save(limits)
        return f"Removed the limit on {app}."
    if not app or parsed["minutes"] < 1:
        raise AutomationError('Say it like "limit valorant to 2 hours a day".')
    limits[app] = parsed["minutes"]
    _save(limits)
    return f"Okay — {_duration(parsed['minutes'])} of {app} a day. I'll tell you {WARN_MINUTES} minutes before, and when it's up."


def due_alerts(log, now: datetime | None = None) -> list[str]:
    """Toasts for the limited app in front right now (blocking: reads the activity log)."""
    now = now or datetime.now()
    app = log.app
    if not app:
        return []
    alerts = []
    today, midnight = now.date().isoformat(), now.replace(hour=0, minute=0, second=0, microsecond=0)
    for name, limit in load().items():
        if name not in app:
            continue
        used = log.app_seconds(name, midnight, now) / 60
        if used >= limit:
            mark = limit + int((used - limit) // OVER_EVERY_MINUTES) * OVER_EVERY_MINUTES
            text = (f"That's your {_duration(limit)} of {name} for today." if mark == limit
                    else f"{_duration(mark - limit)} over your {name} limit today.")
        elif used >= limit - WARN_MINUTES:
            mark, text = limit - WARN_MINUTES, f"{WARN_MINUTES} minutes of {name} left today."
        else:
            continue
        if (name, today, mark) not in _told:
            _told.add((name, today, mark))
            alerts.append(text)
    return alerts
