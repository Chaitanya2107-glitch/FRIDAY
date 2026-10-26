"""
services/activity/habit_patterns.py

The habit engine's learning half (services/activity/habits.py does the suggesting): finds
patterns in the activity log by counting — time habits, chains and routines — and keeps one
per pattern. See habits.py for what each one means.
"""

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from itertools import combinations
from statistics import median
from typing import NamedTuple

from services.activity.categories import BROWSERS

LOOKBACK_DAYS = 14
MIN_DAYS = 3
START_GAP_MINUTES = 30
SAME_TIME_MINUTES = 45            # starts this close are "around the same time"
CHAIN_MINUTES = 2
CHAIN_SHARE = 0.4
BURST_MINUTES = 5
MAX_ROUTINE = 4
# Too general to suggest (sites are instead), or a runtime under the user's own app (catjang runs in electron)
NOT_APPS = BROWSERS | {"explorer", "applicationframehost", "shellhost", "electron", "node", "python", "pythonw"}
APP_NAMES = {"windowsterminal": "Windows Terminal", "whatsapp.root": "WhatsApp", "ms-teams": "Teams",
             "msrdc": "Remote Desktop", "winword": "Word", "powerpnt": "PowerPoint", "code": "VS Code"}  # process → name
APP_OPEN_AS = {"windowsterminal": "windows terminal", "whatsapp.root": "whatsapp", "ms-teams": "teams",
               "code": "vs code", "winword": "word", "powerpnt": "powerpoint"}  # process → what "open …" knows
NOT_SITES = re.compile(r"^(?:www\.)?(?:google|bing|duckduckgo)\.|^(?:accounts|auth|login|clerk|captiveportal)\.|"
                       r":\d+$|^localhost|^127\.", re.I)


class Habit(NamedTuple):
    key: str
    kind: str                 # time, chain or routine
    things: tuple[str, ...]   # "app:code", "site:github.com", "project:catjang" — chain: (trigger, thing)
    days: int                 # days the pattern held
    observed: int             # days it could have
    minute: int | None = None     # time habits and routines: usual minute of the day
    weekend: bool | None = None   # time habits: weekends (True) or weekdays

    @property
    def support(self) -> float:
        return self.days / self.observed if self.observed else 0.0


def starts(rows) -> list[tuple[datetime, str]]:
    """(when, thing) each time a thing is used again after START_GAP_MINUTES without it, oldest first.
    rows: log.habit_rows(), oldest first."""
    last_end: dict[str, datetime] = {}
    found = []
    for at, kind, app, target, seconds, category, project in rows:
        if kind not in ("app", "web"):
            continue
        when = datetime.fromisoformat(at)
        if project:  # the terminal / site is just how the project was worked on
            things = [f"project:{project}"]
        elif kind == "app":
            things = [f"app:{app}"] if app and app not in NOT_APPS and category != "system" else []
        else:
            things = [f"site:{target}"] if target and not NOT_SITES.search(target) else []
        end = when + timedelta(seconds=seconds or 0)
        for thing in things:
            if thing not in last_end or when - last_end[thing] > timedelta(minutes=START_GAP_MINUTES):
                found.append((when, thing))
            last_end[thing] = max(end, last_end.get(thing, end))
    return sorted(found)


def time_habits(found, active_days: set[date]) -> list[Habit]:
    """Things started around the same time of day on MIN_DAYS+ days (weekdays and weekends apart)."""
    # ponytail: one time per thing and day type, and no wrap past midnight
    by_thing: dict[tuple[str, bool], list[tuple[date, int]]] = defaultdict(list)
    for when, thing in found:
        by_thing[(thing, when.weekday() >= 5)].append((when.date(), when.hour * 60 + when.minute))
    habits = []
    for (thing, weekend), times in by_thing.items():
        best: dict[date, int] = {}
        for _, center in times:
            near: dict[date, int] = {}
            for day, minute in times:
                if abs(minute - center) <= SAME_TIME_MINUTES and abs(minute - center) < abs(near.get(day, 10_000) - center):
                    near[day] = minute
            if len(near) > len(best):
                best = near
        if len(best) >= MIN_DAYS:
            observed = sum(1 for d in active_days if (d.weekday() >= 5) == weekend)
            habits.append(Habit(f"time:{thing}:{'weekend' if weekend else 'weekday'}", "time", (thing,), len(best),
                                max(observed, len(best)), int(median(best.values())), weekend))
    return habits


def chains(found) -> list[Habit]:
    """Y started within CHAIN_MINUTES after X, on MIN_DAYS+ days and in CHAIN_SHARE+ of X's starts."""
    starts_of, days_of = Counter(), defaultdict(set)
    pairs, pair_days = Counter(), defaultdict(set)
    for i, (when, x) in enumerate(found):
        if x.startswith("site:"):  # a site starting can't be seen live, so it can't trigger a suggestion
            continue
        starts_of[x] += 1
        days_of[x].add(when.date())
        followers = set()
        for later, y in found[i + 1:]:
            if later - when > timedelta(minutes=CHAIN_MINUTES):
                break
            if later > when and y != x:  # same moment = the same row (an app and its project)
                followers.add(y)
        for y in followers:
            pairs[(x, y)] += 1
            pair_days[(x, y)].add(when.date())
    return [Habit(f"chain:{x}>{y}", "chain", (x, y), len(days), len(days_of[x]))
            for (x, y), days in pair_days.items()
            if len(days) >= MIN_DAYS and pairs[(x, y)] / starts_of[x] >= CHAIN_SHARE]


def routine_habits(launches, used: set[tuple[date, str]]) -> list[Habit]:
    """2–MAX_ROUTINE apps launched within BURST_MINUTES of each other on MIN_DAYS+ days. A launch only counts
    if the user had the app in front that day (programs that start on their own don't)."""
    # ponytail: apps that start with Windows before FRIDAY does aren't seen launching
    bursts: list[tuple[datetime, set[str]]] = []
    first, last, apps = None, None, set()
    for when, app in launches:
        if (when.date(), app) not in used or app in NOT_APPS:
            continue
        if last and when - last > timedelta(minutes=BURST_MINUTES):
            bursts.append((first, apps))
            first, apps = None, set()
        first, last = first or when, when
        apps.add(app)
    if apps:
        bursts.append((first, apps))
    seen: dict[tuple[str, ...], dict[date, int]] = defaultdict(dict)
    for when, burst in bursts:
        names = sorted(burst)[:8]
        for size in range(2, min(MAX_ROUTINE, len(names)) + 1):
            for combo in combinations(names, size):
                seen[combo].setdefault(when.date(), when.hour * 60 + when.minute)
    kept: list[tuple[str, ...]] = []
    for combo in sorted((c for c, d in seen.items() if len(d) >= MIN_DAYS), key=lambda c: (-len(c), -len(seen[c]))):
        if not any(set(combo) <= set(k) for k in kept):
            kept.append(combo)
    observed = len({when.date() for when, _ in launches})
    return [Habit(f"routine:{'+'.join(c)}", "routine", tuple(f"app:{a}" for a in c), len(seen[c]),
                  max(observed, len(seen[c])), int(median(seen[c].values()))) for c in kept]


def prune(habits: list[Habit]) -> list[Habit]:
    """One suggestion per pattern: a routine covers the chains inside it and its apps' times (except the
    first one's), and a chain's second thing doesn't need its own time."""
    groups = [set(h.things) for h in habits if h.kind == "routine"]
    kept_chains = [h for h in habits if h.kind == "chain" and not any(set(h.things) <= g for g in groups)]
    drop = {h.things[1] for h in kept_chains}
    times = [h for h in habits if h.kind == "time"]
    for group in groups:
        members = sorted((h.minute, h.things[0]) for h in times if h.things[0] in group)
        drop |= {thing for _, thing in members[1:]}
    return [h for h in habits if h.kind == "routine"] + kept_chains + [h for h in times if h.things[0] not in drop]


def learn(rows) -> tuple[list[Habit], dict[str, datetime]]:
    """Every habit in these rows, and when each thing was last started."""
    found = starts(rows)
    app_rows = [(datetime.fromisoformat(r[0]), r[2]) for r in rows if r[1] == "app"]
    launches = [(datetime.fromisoformat(r[0]), r[2]) for r in rows if r[1] == "launch"]
    habits = (time_habits(found, {when.date() for when, _ in app_rows}) + chains(found)
              + routine_habits(launches, {(when.date(), app) for when, app in app_rows}))
    return prune(habits), {thing: when for when, thing in found}
