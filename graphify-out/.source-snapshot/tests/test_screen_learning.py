from datetime import datetime, timedelta

import pytest

from services.mind.cognition import Cognition
from services.screen_watch.store import ScreenStore

NOW = datetime(2026, 10, 29, 18)


@pytest.fixture
def store(tmp_path):
    value = ScreenStore(Cognition(tmp_path / "observations.db"))
    value.control("start")
    return value


def seen(store, when=NOW, **updates):
    item = dict(epoch=store.settings()["epoch"], session="one", generation=1,
                scope={"hwnd": 1, "url_hash": "page", "content_hash": "one"}, app="reader",
                summary="Lecture notes are visible.", activity="May be reading.", subject="Graph Theory",
                kind="reading", source="accessible_text", at=when)
    item.update(updates)
    return store.save(**item)


def test_learning_happens_on_background_save_without_a_query(store):
    seen(store)
    with store.db() as conn:
        row = conn.execute("SELECT * FROM screen_activity_days").fetchone()
        assert row["subject"] == "graph theory" and row["exposures"] == 1
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='owner_activities'").fetchone()
    assert store.learned_context(NOW)["recent_activities"][0]["subject"] == "graph theory"


def test_many_checks_are_one_exposure_and_not_a_learned_habit(store):
    for second in range(205):
        seen(store, NOW + timedelta(seconds=second))
    with store.db() as conn:
        row = conn.execute("SELECT * FROM screen_activity_days").fetchone()
        assert row["checks"] == 205 and row["exposures"] == 1 and row["seconds"] == 204
        assert conn.execute("SELECT COUNT(*) FROM screen_observations").fetchone()[0] == 200
    assert store.learned_context(NOW + timedelta(minutes=4))["observed_patterns"] == []


@pytest.mark.parametrize("change", ["generation", "session", "epoch", "page", "interlude"])
def test_real_context_breaks_start_a_new_exposure_without_counting_the_gap(store, change):
    seen(store)
    seen(store, NOW + timedelta(seconds=30))
    updates = {}
    if change == "epoch":
        store.control("pause")
        store.control("resume")
    elif change == "page":
        updates["scope"] = {"hwnd": 1, "url_hash": "different", "content_hash": "one"}
    elif change == "interlude":
        seen(store, NOW + timedelta(seconds=35), subject="biology")
    else:
        updates[change] = 2 if change == "generation" else "two"
    seen(store, NOW + timedelta(seconds=60), **updates)
    with store.db() as conn:
        row = conn.execute("SELECT * FROM screen_activity_days WHERE subject='graph theory'").fetchone()
        assert row["exposures"] == 2 and row["seconds"] == 30


def test_recurrence_requires_three_supported_days_and_survives_short_cache_eviction(store):
    for days_ago in (2, 1, 0):
        for seconds in (0, 30, 60):
            seen(store, NOW - timedelta(days=days_ago) + timedelta(seconds=seconds))
    for second in range(210):
        seen(store, NOW + timedelta(minutes=2, seconds=second), app="other", subject="", kind="unknown")
    view = store.learned_context(NOW + timedelta(minutes=6))
    assert all(r["app"] == "other" for r in view["recent_observations"])
    pattern = view["observed_patterns"][0]
    assert pattern["days"] == 3 and pattern["exposures"] == 3
    assert pattern["observed_period"] == "evening"
    assert "not a confirmed preference" in pattern["status"]


def test_forget_matches_subject_and_clears_derived_patterns_even_after_cache_eviction(store):
    for days_ago in (2, 1, 0):
        for seconds in (0, 30, 60):
            seen(store, NOW - timedelta(days=days_ago) + timedelta(seconds=seconds), subject="combinatorics")
    for second in range(205):
        seen(store, NOW + timedelta(minutes=2, seconds=second), subject="biology")
    assert store.learned_context(NOW + timedelta(minutes=6))["observed_patterns"]
    assert store.forget("combinatorics")
    view = store.learned_context(NOW + timedelta(minutes=6))
    assert all(r["subject"] != "combinatorics" for r in view["recent_observations"] + view["recent_activities"])
    assert not view["observed_patterns"]
    assert view["recent_activities"][0]["subject"] == "biology"
    assert store.settings()["paused"]


def test_forget_removes_learning_derived_from_an_older_matching_summary(store):
    seen(store, summary="A lecture featuring Alice is visible.")
    seen(store, NOW + timedelta(seconds=30), summary="A lecture featuring Bob is visible.")
    seen(store, NOW + timedelta(seconds=60), summary="Biology lecture.", subject="biology")
    assert store.forget("Alice")
    view = store.learned_context(NOW + timedelta(minutes=2))
    assert [row["subject"] for row in view["recent_activities"]] == ["biology"]


def test_retention_and_existing_global_forget_cover_passive_learning(store):
    from services.mind.executive import clear_derived
    seen(store)
    store.prune(NOW + timedelta(days=8))
    assert not any(store.learned_context(NOW + timedelta(days=8)).values())
    seen(store, NOW + timedelta(days=8))
    with store.db() as conn:
        clear_derived(conn)
    assert not any(store.learned_context(NOW + timedelta(days=8)).values())


def test_pause_fences_both_observation_and_learning_commit(store):
    epoch = store.settings()["epoch"]
    store.control("pause")
    assert not seen(store, epoch=epoch)
    assert not any(store.learned_context(NOW).values())
