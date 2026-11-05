"""
services/proactive/nudges.py

Decides when to nudge the user, from one reading of the system per minute:
  - battery at 20% or less and not charging (urgent at 10%: shown even while gaming)
  - GPU at 85°C+ or memory at 85%+ for 3 readings in a row
  - one app in the foreground for LONG_APP_HOURS without a break
  - drive C under 20 GB free (at most once a day)
  - eye breaks, only when switched on ("turn on eye breaks"): every EYE_BREAK_MINUTES of
    screen time without a 2-minute break, "look 20 feet away for 20 seconds" (20-20-20)
(Habit suggestions are services/activity/habits.py.)

Each nudge fires once per episode, and again only after the problem has gone
away (charged, cooled down, took a break). Reading the system is separate
(read_system) so the rules can be tested with made-up readings.
"""

from datetime import date, datetime
from typing import NamedTuple

import psutil

from core.config import config
from core.logger import logger
from services.activity.log import activity_log
from services.automation import system_stats

LOW_BATTERY = system_stats.LOW_BATTERY
CRITICAL_BATTERY = 10
BATTERY_OK_AGAIN = 25
SUSTAINED_READINGS = 3
EYE_BREAK_MINUTES = 20


class Readings(NamedTuple):
    battery: float | None = None       # percent; None = no battery
    plugged_in: bool = True
    memory: float = 0.0                # percent used
    top_memory_app: str | None = None  # only read when memory is high
    gpu_temperature: int | None = None
    disk_free_gb: float = 1000.0
    app: str | None = None             # foreground app, None when idle
    app_since: datetime | None = None


class Nudge(NamedTuple):
    text: str
    urgent: bool = False  # urgent nudges are shown even while the user is gaming / fullscreen
    keep: bool = True     # False: dropped, not held, while gaming / fullscreen (stale by then)


def read_system() -> Readings:
    """One reading (blocking, up to a few seconds for nvidia-smi)."""
    battery = psutil.sensors_battery()
    memory = psutil.virtual_memory().percent
    top = None
    if memory >= system_stats.HIGH_MEMORY:
        apps = system_stats._top_apps("memory")
        top = apps[0][0] if apps else None
    temperatures = [g.temperature for g in system_stats._gpus() if g.temperature is not None]
    return Readings(
        battery=battery.percent if battery else None,
        plugged_in=battery.power_plugged if battery else True,
        memory=memory,
        top_memory_app=top,
        gpu_temperature=max(temperatures, default=None),
        disk_free_gb=psutil.disk_usage(system_stats.SYSTEM_DRIVE).free / system_stats.GB,
        app=activity_log.app,
        app_since=activity_log.app_since,
    )


class Nudger:
    def __init__(self):
        self._fired: set[str] = set()
        self._streaks = {"gpu": 0, "memory": 0}
        self._disk_warned_on: date | None = None
        self._screen_since: datetime | None = None  # at the screen without a break since

    def check(self, r: Readings, now: datetime, eye_breaks: bool = False) -> list[Nudge]:
        nudges = [self._battery(r), self._gpu(r), self._memory(r), self._long_stretch(r, now), self._disk(r, now),
                  self._eye_break(r, now, eye_breaks)]
        return [n for n in nudges if n]

    def _eye_break(self, r: Readings, now: datetime, on: bool) -> Nudge | None:
        if not (on and r.app):  # idle (2+ min away) is the break
            self._screen_since = None
            return None
        self._screen_since = self._screen_since or now
        if (now - self._screen_since).total_seconds() < EYE_BREAK_MINUTES * 60:
            return None
        self._screen_since = now
        return Nudge("Eye break: look at something 20 feet away for 20 seconds.", keep=False)

    def _once(self, key: str, nudge: Nudge) -> Nudge | None:
        if key in self._fired:
            return None
        self._fired.add(key)
        logger.info(f"Nudge: {nudge.text}")
        return nudge

    def _battery(self, r: Readings) -> Nudge | None:
        if r.battery is None or r.plugged_in or r.battery > BATTERY_OK_AGAIN:
            self._fired -= {"battery", "battery_critical"}
            return None
        if r.battery <= CRITICAL_BATTERY:
            self._fired.add("battery")  # no separate "low" nudge after the critical one
            return self._once("battery_critical", Nudge(
                f"Battery is at {r.battery:.0f}% — plug in now or the laptop will shut down soon.", urgent=True,
            ))
        if r.battery <= LOW_BATTERY:
            return self._once("battery", Nudge(f"Battery is at {r.battery:.0f}%. Plug in soon."))
        return None

    def _sustained(self, key: str, high: bool) -> bool:
        """True once `high` has held for SUSTAINED_READINGS readings in a row."""
        self._streaks[key] = self._streaks[key] + 1 if high else 0
        if not high:
            self._fired.discard(key)
        return self._streaks[key] >= SUSTAINED_READINGS

    def _gpu(self, r: Readings) -> Nudge | None:
        hot = r.gpu_temperature is not None and r.gpu_temperature >= system_stats.HOT_GPU
        if self._sustained("gpu", hot):
            return self._once("gpu", Nudge(
                f"Your GPU has been at {r.gpu_temperature}°C for a few minutes. "
                "Maybe close a game or give the laptop some air."
            ))
        return None

    def _memory(self, r: Readings) -> Nudge | None:
        if self._sustained("memory", r.memory >= system_stats.HIGH_MEMORY):
            culprit = f" {r.top_memory_app} is using the most." if r.top_memory_app else ""
            return self._once("memory", Nudge(f"Memory is {r.memory:.0f}% full.{culprit}"))
        return None

    def _long_stretch(self, r: Readings, now: datetime) -> Nudge | None:
        if not (r.app and r.app_since):
            return None
        hours = (now - r.app_since).total_seconds() / 3600
        if hours < config.LONG_APP_HOURS:
            return None
        # One nudge per stretch: a new stretch (after switching or a break) starts at a new time
        return self._once(f"app:{r.app}:{r.app_since.isoformat()}", Nudge(
            f"You've been in {r.app} for {int(hours)} hours straight. Time for a short break?"
        ))

    def _disk(self, r: Readings, now: datetime) -> Nudge | None:
        if r.disk_free_gb >= system_stats.LOW_DISK_GB or self._disk_warned_on == now.date():
            return None
        self._disk_warned_on = now.date()
        return Nudge(f"Drive C is nearly full — only {r.disk_free_gb:.0f} GB left.")
