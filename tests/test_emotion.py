from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.mood.engine import MoodEngine
from services.mind import emotion, life, state


NOW = datetime(2026, 11, 18, 13)
HALF_LIFE = timedelta(hours=3)


def present(idle=0, *, battery=None, situation=None):
    return dict(idle=idle, battery=battery, situation=situation or {})


def test_replay_moves_dimensions_and_halves_the_difference_every_three_hours():
    now = NOW.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    baseline = emotion.snapshot(now)
    assert emotion.record("task_finished", now)
    full, half = emotion.snapshot(now), emotion.snapshot(now + HALF_LIFE)
    assert full["band"] == "bright" and full["face"] == "happy"
    for dimension in ("valence", "arousal", "warmth", "curiosity"):
        assert half[dimension] == pytest.approx((full[dimension] + baseline[dimension]) / 2)
        assert 0 <= full[dimension] <= 1
    assert emotion.snapshot(now - timedelta(seconds=1)) == baseline
    assert emotion.snapshot(now + timedelta(days=3)) == baseline
    assert json.loads(emotion.storage_path().read_text(encoding="utf-8"))["events"] == [
        {"kind": "task_finished", "at": now.timestamp()}
    ]


def test_return_and_quiet_cannot_reduce_warmth_or_presume_rejection():
    life.feel("answered", NOW.timestamp())
    life.feel("shushed", NOW.timestamp())
    life.feel("ignored", NOW.timestamp())
    warmth = emotion.snapshot(NOW)["warmth"]
    observer = emotion.Observer()
    observer.observe(NOW, present(idle=emotion.RETURN_SECONDS + 2), [])
    assert life.mood(NOW, away_minutes=90) == ("quiet", "respecting time away from the laptop")
    assert emotion.snapshot(NOW)["warmth"] == warmth
    assert not emotion.storage_path().exists()

    observer.observe(NOW, present(), [])
    actual = emotion.snapshot(NOW)
    assert actual["warmth"] > warmth
    assert actual["drives"]["glad_you_are_back"] > 0
    assert actual["face"] == "waving"
    assert life.mood(NOW) == ("pleased", "ready to pick things up again")


def test_legacy_counters_contribute_only_after_their_receipt():
    before = emotion.snapshot(NOW)
    later = NOW + timedelta(minutes=1)
    life.feel("noticed", later.timestamp())
    assert emotion.snapshot(NOW) == before
    assert emotion.snapshot(later)["curiosity"] > before["curiosity"]


@pytest.mark.parametrize("text, expected", [
    ("FRIDAY, I'm really stressed about the exam tomorrow", True),
    ("I am feeling stressed out", True),
    ("my exam is stressing me out.", True),
    ("I am not stressed", False),
    ("If I'm stressed later", False),
    ("Type I'm stressed", False),
    ("Tell me what 'I am stressed' means", False),
    ("Am I stressed?", False),
    ("I'm stressed?", False),
    ("I'm stressed only when I drive", False),
    ("I am stressed-free", False),
    ("My friend is feeling stressed", False),
])
def test_only_explicit_stress_disclosure_is_matched(text, expected):
    assert emotion.is_stress_statement(text) is expected


def test_stress_updates_cached_tone_without_touching_posture_or_prompt_inputs():
    emotion.record("exam_close", NOW)
    before = state.snapshot(NOW)
    assert before["emotion"]["band"] == "focused"
    assert emotion.note_owner("I feel stressed about the exam", NOW) == "owner_stressed"
    after = state.snapshot(NOW)
    assert before is not after
    assert before["life_state"] == after["life_state"]
    assert before["live"] == after["live"]
    assert after["emotion"]["owner_stressed"] and after["emotion"]["chatty"] <= .25
    assert after["mood"] == "calm"
    saved = json.loads(emotion.storage_path().read_text(encoding="utf-8"))["events"]
    assert saved[-1] == {"kind": "owner_stressed", "at": NOW.timestamp()}
    assert not emotion.snapshot(NOW + 2 * HALF_LIFE)["owner_stressed"]


def test_praise_and_correction_never_reduce_warmth_or_blame_the_owner():
    assert emotion.note_owner("Good job, Friday!", NOW) == "praise"
    praised = emotion.snapshot(NOW)
    assert praised["valence"] > emotion.BASELINE["valence"]
    assert emotion.note_owner("No, I said Spotify", NOW) == "correction"
    corrected = emotion.snapshot(NOW)
    assert corrected["warmth"] == praised["warmth"]
    assert corrected["valence"] == praised["valence"]
    assert corrected["arousal"] < praised["arousal"]
    assert corrected["drives"]["wanting_to_help"] > praised["drives"]["wanting_to_help"]
    assert "Spotify" not in emotion.storage_path().read_text(encoding="utf-8")


def test_sensors_record_late_battery_and_exams_once_per_occurrence():
    now = NOW.replace(hour=2)
    observer = emotion.Observer()
    exam = SimpleNamespace(id="private exam ID", due_at=now + timedelta(hours=8))
    reading = present(battery={"percent": 19, "plugged": False})
    observer.observe(now, reading, [exam])
    observer.observe(now + timedelta(minutes=1), reading, [exam])
    next_day = now + timedelta(days=1)
    observer.observe(next_day, present(situation={
        "current": [{"id": "private date report", "status": "planned", "start": str(next_day.date()),
                     "end": str(next_day.date()), "subject": "Math exam"}],
    }), [])
    assert emotion.snapshot(now)["drives"]["tiredness"] > emotion.BASELINE["tiredness"]
    raw = emotion.storage_path().read_text(encoding="utf-8")
    assert "private" not in raw and "Math" not in raw
    assert [row["kind"] for row in json.loads(raw)["events"]] == [
        "late_night", "low_battery", "exam_close", "late_night", "exam_close",
    ]


def test_completion_requires_real_receipt_after_the_task_is_saved(monkeypatch):
    from services import event_bus
    from services.mind.workspace import workspace

    def publish(topic, data):
        assert workspace.tasks(include_finished=True)[0]["status"] == "completed"
        emotion._completion(dict(topic=topic, payload=data, plugin_id="friday", at=NOW.timestamp()))

    monkeypatch.setattr(event_bus, "publish", publish)
    task = workspace.start_task("Private task")
    workspace.plan(task, ["Write", "Check"])
    workspace.advance(task, "Done writing")
    assert not emotion.storage_path().exists()
    workspace.advance(task, "Verified")
    assert emotion.snapshot(NOW)["band"] == "bright"
    stopped = {"completed": False, "phase": "focus", "session_id": "focus:x"}
    for payload, plugin in [(stopped, "focus"), ({**stopped, "completed": True}, "other"),
                            ({**stopped, "completed": True, "phase": "break"}, "focus")]:
        emotion._completion(dict(topic="focus.done", payload=payload, plugin_id=plugin, at=NOW.timestamp()))
    assert len(json.loads(emotion.storage_path().read_text(encoding="utf-8"))["events"]) == 1
    delivered = dict(topic="focus.done", payload={**stopped, "completed": True},
                     plugin_id="focus", at=NOW.timestamp())
    emotion._completion(delivered)
    emotion._completion(delivered)
    assert len(json.loads(emotion.storage_path().read_text(encoding="utf-8"))["events"]) == 2


def test_mochi_uses_persona_face_beneath_alerts_and_quiet(monkeypatch):
    emitted = []
    settings = {}
    clock = [NOW.timestamp()]
    api = SimpleNamespace(settings=settings, log=logging.getLogger("test.persona"),
                          publish=lambda topic, value: emitted.append((topic, value)))
    rules = Path(__file__).resolve().parents[1] / "plugins" / "mood" / "mood_rules.json"
    mochi = MoodEngine(api, rules, clock=lambda: clock[0])

    def publish(topic, payload):
        mochi.receive(dict(topic=topic, payload=payload, plugin_id="friday"))

    monkeypatch.setattr(emotion.event_bus, "publish", publish)
    monkeypatch.setattr(emotion.event_bus, "recent", lambda _: [])
    assert emotion.note_owner("Good job", NOW) == "praise"
    assert emitted[-1][0] == "mood.changed" and emitted[-1][1]["mood"] == "happy"
    assert not emitted[-1][1]["message"]
    mochi.receive(dict(topic="battery.critical", payload={}, plugin_id="system_events"))
    assert mochi.current["mood"] == "alarmed"
    clock[0] += 16
    mochi.tick()
    assert mochi.current["mood"] == "happy"
    settings["mood.calm_mode"] = True
    mochi.tick()
    assert mochi.current["mood"] == "idle"
    settings["mood.calm_mode"] = False
    emotion.publish_face(NOW + timedelta(hours=8), refresh=True)
    assert mochi.current["mood"] == "idle"
    emotion.publish_face(NOW + timedelta(hours=10), refresh=True)
    assert mochi.current["mood"] == "sleepy"
