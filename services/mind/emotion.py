"""Replay local persona events into tone and animation. No action policy lives here."""

import asyncio
import hashlib
import json
import math
import re
import time
from datetime import date, datetime, timedelta

from core.logger import logger
from services import settings_store
from services.event_bus import event_bus
from services.mind import life

BASELINE = dict(valence=.54, arousal=.36, warmth=.45, curiosity=.15,
                wanting_to_help=.50, tiredness=.08, glad_you_are_back=0.)
EVENTS = {
    "task_finished": dict(valence=.20, arousal=.14, warmth=.10),
    "exam_close": dict(arousal=.10, wanting_to_help=.24),
    "praise": dict(valence=.17, warmth=.15),
    "correction": dict(arousal=-.08, wanting_to_help=.10),
    "late_night": dict(valence=-.04, arousal=-.12, tiredness=.30),
    "low_battery": dict(valence=-.09, arousal=.06, wanting_to_help=.10),
    "long_absence": dict(valence=.16, warmth=.16, glad_you_are_back=.36),
    "owner_stressed": dict(arousal=-.15, warmth=.05, wanting_to_help=.25),
}
HALF_LIFE_SECONDS = life.HALF_LIFE_HOURS * 3600
HISTORY_SECONDS = 7 * 86400
RETURN_SECONDS = life.AWAY_MINUTES * 60
WELCOME_SECONDS = 10 * 60
SAMPLE_SECONDS = 30
_STRESS = re.compile(
    r"(?:(?:i am|i'm|i feel|i've been feeling)(?: (?:feeling|very|really|so|quite|pretty|extremely)){0,3}"
    r" stressed(?: out)?|(?:my|the) (?:exam|test|assessment) is stressing me out)"
    r"(?=$|[,!.]| (?:about|before|because|from|right now|today|over|with)\b)", re.I,
)
_PRAISE = re.compile(r"(?:nice work|good job|(?:thanks|thank you),? friday|that helped|you're amazing)(?:[ .!,]|$)", re.I)
_CORRECTION = re.compile(r"(?:that's wrong|you got that wrong|(?:(?:no|actually),? )?i meant\b|no,? i said\b)", re.I)
_RECEIPTS = ("focus.done", "workspace.task_completed")


def storage_path():
    return life.path.with_name("emotion.json")


def _timestamp(now):
    return time.time() if now is None else now.timestamp() if isinstance(now, datetime) else float(now)


def _events():
    try:
        data = json.loads(storage_path().read_text(encoding="utf-8"))
        events = data.get("events", []) if isinstance(data, dict) else []
        if not isinstance(events, list):
            return []
        return [row for row in events if isinstance(row, dict) and isinstance(row.get("kind"), str)
                and row["kind"] in EVENTS and type(row.get("at")) in (int, float) and math.isfinite(row["at"])]
    except (OSError, ValueError, OverflowError):
        return []


def _fade(seconds):
    return .5 ** (seconds / HALF_LIFE_SECONDS)


def _bounded(value):
    return max(0., min(1., value))


def snapshot(now=None, *, daily_rhythm=None):
    """Deterministic 0–1 levels and presentation hints at the given instant."""
    stamp = _timestamp(now)
    events = sorted((row for row in _events() if stamp - HISTORY_SECONDS <= row["at"] <= stamp),
                    key=lambda row: row["at"])
    levels = BASELINE.copy()
    previous, stress_at, return_at = stamp - HISTORY_SECONDS, float("-inf"), None
    for row in events:
        at, kind = row["at"], row["kind"]
        keep = _fade(at - previous)
        for key, base in BASELINE.items():
            levels[key] = _bounded(base + (levels[key] - base) * keep + EVENTS[kind].get(key, 0.))
        if kind == "owner_stressed":
            stress_at = at
        if kind == "long_absence":
            return_at = at
        previous = at
    keep = _fade(stamp - previous)
    for key, base in BASELINE.items():
        levels[key] = base + (levels[key] - base) * keep

    counters = life.load()
    if counters.get("at", stamp) <= stamp:
        warmth, curiosity = life._faded(counters, stamp)
        levels["warmth"] = _bounded(levels["warmth"] + .20 * warmth)
        levels["curiosity"] = _bounded(levels["curiosity"] + .25 * max(0., curiosity))
    if daily_rhythm is None:
        from services.mind import rhythm
        daily_rhythm = rhythm.current(now if isinstance(now, datetime) else datetime.fromtimestamp(stamp))
    levels['tiredness'] = max(levels['tiredness'], daily_rhythm['tiredness'])
    valence, arousal = levels["valence"], levels["arousal"]
    stressed = stamp - stress_at < 2 * HALF_LIFE_SECONDS
    if return_at is not None and stamp - return_at >= WELCOME_SECONDS:
        return_at = None
    if stressed:
        band, face = "calm", "focused"
    elif levels["tiredness"] >= .24:
        band, face = "calm", "sleepy"
    elif levels["wanting_to_help"] >= .62 and arousal >= .41:
        band, face = "focused", "focused"
    elif valence >= .65:
        band, face = "bright", "waving" if return_at is not None else "happy"
    elif arousal < .30:
        band, face = "calm", "idle"
    else:
        band = "neutral"
        face = "curious" if levels["curiosity"] >= .525 else "happy" if levels["warmth"] >= .65 else "idle"
    chatty = min(.25, arousal) if band in {"calm", "focused"} else _bounded(arousal + (valence - .54))
    drives = {key: round(levels[key], 6) for key in ("curiosity", "wanting_to_help", "tiredness", "glad_you_are_back")}
    return {key: round(levels[key], 6) for key in ("valence", "arousal", "warmth", "curiosity")} | {
        "drives": drives, "band": band, "owner_stressed": stressed, "chatty": round(chatty, 6), "face": face,
        "return_at": return_at,
    }


def publish_face(now=None, *, refresh=False):
    """Publish only the face. Mochi keeps the final say on display priority."""
    from services.remote.context import remote_origin

    if remote_origin.get():
        return
    with settings_store.lock:
        face = snapshot(now)["face"]
        recent = event_bus.recent("mood.persona")
        previous = next((row["payload"].get("face") for row in reversed(recent) if row["plugin_id"] == "friday"), "idle")
        if refresh or face != previous:
            event_bus.publish("mood.persona", {"face": face})


def record(kind, now=None, *, occurrence=None, gap=0):
    """Write a named event with an optional dedupe key. Raw owner words stay out."""
    if kind not in EVENTS:
        raise ValueError(f"Unknown persona event {kind}")
    stamp = _timestamp(now)
    if not math.isfinite(stamp):
        raise ValueError("Invalid persona event time")
    reference = hashlib.sha256(occurrence.encode("utf-8")).hexdigest() if occurrence is not None else None
    try:
        with settings_store.lock:
            events = [row for row in _events() if row["at"] >= stamp - HISTORY_SECONDS]
            if any(row["kind"] == kind and (
                    reference is not None and row.get("ref") == reference
                    or gap and 0 <= stamp - row["at"] < gap)
                   for row in events):
                return False
            event = {"kind": kind, "at": stamp}
            if reference is not None:
                event["ref"] = reference
            settings_store.save(storage_path(), {"version": 1, "events": [*events, event]})
            publish_face(stamp)
    except (OSError, ValueError):
        logger.debug("Persona event storage unavailable")
        return False
    return True


def _owner_text(text):
    from services.automation.command_words import strip_leading_filler

    return strip_leading_filler(text[:1000])


def is_stress_statement(text):
    clean = _owner_text(text)
    return not clean.rstrip().endswith("?") and bool(_STRESS.match(clean))


def is_standalone_stress(text):
    clean = _owner_text(text).strip().rstrip(".!")
    return (is_stress_statement(clean) and not re.search(
        r"[,;:.!\n?]|\b(?:please|(?:can|could|would|will) you|(?:and|then) (?:set|start|stop|remind|send|open|save|add))\b",
        clean, re.I))


def note_owner(text, now=None):
    from services.automation.intent import remote_request
    from services.remote.context import remote_origin

    if remote_request.get() or remote_origin.get():
        return None
    clean = _owner_text(text)
    kind = ("owner_stressed" if is_stress_statement(text) else "praise" if _PRAISE.match(clean)
            else "correction" if _CORRECTION.match(clean) else None)
    if kind:
        record(kind, now)
    return kind


def _completion(event):
    topic, data, source = event["topic"], event["payload"], event["plugin_id"]
    if topic == "workspace.task_completed" and source == "friday":
        record("task_finished", event["at"])
    elif (source == "focus" and data.get("completed") is True and data.get("phase") == "focus"
          and isinstance(data.get("session_id"), str)):
        record("task_finished", event["at"], occurrence="focus:" + data["session_id"])


class Observer:
    """Translate trusted snapshots into edges, keeping only the previous edge state."""

    def __init__(self):
        self.away = self.low_battery = False

    def observe(self, now, present, exams):
        idle = present["idle"]
        if idle >= RETURN_SECONDS:
            self.away = True
        elif self.away and idle < 120:
            record("long_absence", now)
            self.away = False
        if idle < 120 and 1 <= now.hour < 6:
            record("late_night", now, occurrence=now.date().isoformat())

        battery = present.get("battery") or {}
        percent = battery.get("percent")
        if type(percent) in (int, float) and 0 <= percent <= 100 and type(battery.get("plugged")) is bool:
            if battery["plugged"] or percent > 25:
                self.low_battery = False
            elif not self.low_battery and percent <= 20:
                record("low_battery", now, gap=HALF_LIFE_SECONDS)
                self.low_battery = True

        from services.proactive.college import EXAM_WORDS

        if exams:
            exam = exams[0]
            record("exam_close", now, occurrence=f"schedule:{exam.id}:{exam.due_at.isoformat()}")
        else:
            today = now.date()
            situation = present["situation"]
            for row in (*situation.get("current", ()), *situation.get("upcoming", ())):
                if (row.get("status") in {"planned", "postponed"} and row.get("start") == row.get("end")
                        and EXAM_WORDS.search(row.get("subject", "")) and row.get("start")
                        and today <= date.fromisoformat(row["start"]) <= today + timedelta(days=1)):
                    record("exam_close", now, occurrence=f"temporal:{row['id']}:{row['start']}")
                    break
        publish_face(now, refresh=True)

    def sample(self):
        from services.mind import state
        from services.schedule_adapter import ScheduleAdapter

        now = datetime.now()
        self.observe(now, state.snapshot(now), ScheduleAdapter(now=lambda: now).upcoming_exams(1))


async def run():
    """Persona observation runs independently of alerts, scheduling and user input."""
    observer = Observer()
    subscriptions = [event_bus.subscribe(topic, _completion, plugin_id="emotion") for topic in _RECEIPTS]
    try:
        while True:
            try:
                await asyncio.to_thread(observer.sample)
            except Exception as error:
                logger.debug("Persona observation unavailable (%s)", type(error).__name__)
            await asyncio.sleep(SAMPLE_SECONDS)
    finally:
        for subscription in subscriptions:
            event_bus.unsubscribe(subscription)
