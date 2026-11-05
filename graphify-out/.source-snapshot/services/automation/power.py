"""
services/automation/power.py

The laptop's power, by voice, the command bar or Telegram (/lock, /sleep, /shutdown 30):
  "lock the laptop" (at once), "put the laptop to sleep", "shut down (in 30 minutes)",
  "restart the laptop", "cancel the shutdown" — sleep, shutdown and restart ask first (intent.py).
  "I'm going out" / "/away": pause what's playing, lock, and send notifications to Telegram
  straight away (not after TELEGRAM_AWAY_MINUTES) until you're back at the laptop.
"""

import ctypes
import re
import subprocess
import threading
import time

from core.logger import logger

POWER_ACTIONS = {"lock_pc", "sleep_pc", "shutdown_pc", "restart_pc", "cancel_shutdown", "away"}
ASK_FIRST = {"sleep_pc", "shutdown_pc", "restart_pc"}
DELAY_SECONDS = 2  # so the reply is shown / spoken / sent before the laptop goes

_PC = r"(?:\s+(?:the|my|this)?\s*(?:laptop|pc|computer|system|machine))?"
_LOCK = re.compile(rf"^lock{_PC}(?:\s+screen)?$|^lock (?:the |my )?screen$|^lock it$", re.I)
_SLEEP = re.compile(rf"^(?:put{_PC} to sleep|sleep{_PC}|go to sleep|sleep now|hibernate{_PC})$", re.I)
_SHUTDOWN = re.compile(rf"^(?:shut ?down|turn off|power off|switch off){_PC}(?:\s+in\s+(?P<n>\d+)\s*(?P<unit>minutes?|mins?|hours?|hrs?|seconds?|secs?))?$", re.I)
_RESTART = re.compile(rf"^(?:restart|reboot){_PC}(?:\s+in\s+(?P<n>\d+)\s*(?P<unit>minutes?|mins?|hours?|hrs?))?$", re.I)
_CANCEL = re.compile(r"^(?:cancel|abort|stop) (?:the )?(?:shut ?down|restart|reboot)$", re.I)
_AWAY = re.compile(r"^(?:i'?m|i am) (?:going out|heading out|leaving|stepping out|going away)$|^going out$|^away mode$", re.I)


def _seconds(n: str | None, unit: str | None) -> int:
    if not n:
        return 0
    unit = (unit or "m").lower()
    return int(n) * (3600 if unit.startswith("h") else 1 if unit.startswith("s") else 60)


def match_power_command(text: str) -> dict | None:
    """`text` has been through normalize_command(). "shut down spotify" is closing an app, not this."""
    text = text.strip().rstrip(".!")
    if _LOCK.match(text):
        return {"type": "system", "action": "lock_pc"}
    if _SLEEP.match(text):
        return {"type": "system", "action": "sleep_pc"}
    if m := _SHUTDOWN.match(text):
        return {"type": "system", "action": "shutdown_pc", "seconds": _seconds(m["n"], m["unit"])}
    if m := _RESTART.match(text):
        return {"type": "system", "action": "restart_pc", "seconds": _seconds(m["n"], m["unit"])}
    if _CANCEL.match(text):
        return {"type": "system", "action": "cancel_shutdown"}
    if _AWAY.match(text):
        return {"type": "system", "action": "away"}
    return None


def question(parsed: dict) -> str:
    """The yes/no question for ASK_FIRST actions."""
    when = f" in {_when(parsed.get('seconds', 0))}" if parsed.get("seconds") else ""
    return {"sleep_pc": "Put the laptop to sleep?", "shutdown_pc": f"Shut down the laptop{when}?",
            "restart_pc": f"Restart the laptop{when}?"}[parsed["action"]] + " Say yes or no."


def _when(seconds: int) -> str:
    return f"{seconds // 3600} h" if seconds >= 3600 and not seconds % 3600 else \
        f"{seconds // 60} min" if seconds >= 60 else f"{seconds} s"


def _later(do) -> None:
    threading.Thread(target=lambda: (time.sleep(DELAY_SECONDS), do()), daemon=True, name="power").start()


def lock() -> None:
    ctypes.windll.user32.LockWorkStation()


def _shutdown(args: list[str]) -> None:
    subprocess.run(["shutdown", *args], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


def run(parsed: dict) -> str:
    action = parsed["action"]
    if action == "lock_pc":
        _later(lock)
        return "Locking."
    if action == "sleep_pc":
        _later(lambda: ctypes.windll.powrprof.SetSuspendState(False, True, False))
        return "Going to sleep."
    if action in ("shutdown_pc", "restart_pc"):
        seconds = max(parsed.get("seconds", 0), DELAY_SECONDS + 3)
        _shutdown(["/s" if action == "shutdown_pc" else "/r", "/t", str(seconds)])
        word = "Shutting down" if action == "shutdown_pc" else "Restarting"
        return f"{word} in {_when(seconds)}." + (' Say "cancel the shutdown" to stop it.' if seconds >= 60 else "")
    if action == "cancel_shutdown":
        _shutdown(["/a"])
        return "Cancelled — nothing is going to shut down."
    return go_away()


def go_away() -> str:
    """Pause what's playing, lock, and send notifications to Telegram straight away until the user is back."""
    from services.automation import media_control
    from services.telegram import client

    try:
        media_control.pause()
    except Exception as e:  # nothing playing / no player: fine
        logger.info(f"Away: nothing paused ({e})")
    client.set_away(True)
    _later(lock)
    return "Away mode: paused, locking, and notifications go to Telegram until you're back."
