from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from services.learning.contracts import PredictionFeedback, Session
from services.learning.dataset import build_examples

NOW = datetime(2026, 10, 12, 12)
START = NOW - timedelta(hours=1)


def session(i, name, **changes):
    row = Session(str(i), START + timedelta(seconds=i * 15), name, 10,
                  origin="user", runtime="run")
    return replace(row, **changes)


def test_observed_times_and_stable_ids():
    rows = [session(0, "a"), session(1, "b"), session(2, "c")]
    first = build_examples(rows, [], NOW)
    assert len(first.examples) == 2
    a, b = first.examples
    assert a.feature_at == rows[0].at
    assert a.label_at == rows[1].at + timedelta(seconds=10)
    assert a.before is None and b.before == "a"
    assert a.source_ids == ("0", "1")
    assert first == build_examples(rows, [], NOW)


@pytest.mark.parametrize("changes", [
    {"status": "excluded"}, {"seconds": 2}, {"seconds": -1},
    {"seconds": float("nan")}, {"origin": "unknown"}, {"origin": "automatic"},
    {"category": "system"}, {"category": "idle"}, {"at": None},
    {"at": NOW + timedelta(hours=1)}, {"app": None},
])
def test_rejected_middle_breaks_transition_and_context(changes):
    rows = [session(0, "a"), session(1, "b", **changes), session(2, "c"), session(3, "d")]
    data = build_examples(rows, [], NOW)
    assert [(e.app, e.nxt, e.before) for e in data.examples] == [("c", "d", None)]
    assert data.reasons


@pytest.mark.parametrize("changes", [{"runtime": "new"}, {"at": START + timedelta(minutes=5)}])
def test_discontinuity_breaks_context(changes):
    rows = [session(0, "a"), session(1, "b"), session(2, "c", **changes)]
    data = build_examples(rows, [], NOW)
    assert [(e.app, e.nxt) for e in data.examples] == [("a", "b")]


def test_continuous_same_app_titles_compress_without_changing_first_feature():
    rows = [session(0, "a"), session(1, "a"), session(2, "b")]
    example, = build_examples(rows, [], NOW).examples
    assert example.source_ids == ("0", "1", "2")
    assert example.feature_at == rows[0].at


def test_confirmation_is_evidence_only_for_observed_matching_outcome():
    rows = [session(0, "a"), session(1, "b")]
    prediction_at = START + timedelta(seconds=3)
    feedback = PredictionFeedback("f", prediction_at, "a", "b", True,
                                  available_at=NOW - timedelta(minutes=1))
    example, = build_examples(rows, [feedback, feedback], NOW).examples
    plain, = build_examples(rows, [], NOW).examples
    assert example.source_id == plain.source_id
    assert example.weight == 3 and example.feedback_ids == ("f",)
    assert example.feature_at == rows[0].at
    assert not build_examples(rows[:1], [feedback], NOW).examples
    for other in (replace(feedback, nxt="c"), replace(feedback, right=False),
                  replace(feedback, available_at=NOW + timedelta(minutes=1)),
                  replace(feedback, before="wrong")):
        assert build_examples(rows, [other], NOW).examples[0].weight == 1


def test_duplicate_identity_and_out_of_order_records_do_not_bridge():
    rows = [session(0, "a"), session(0, "b"), session(2, "c"), session(3, "d")]
    data = build_examples(rows, [], NOW)
    assert [(e.app, e.nxt, e.before) for e in data.examples] == [("c", "d", None)]


def test_forecast_snapshot_does_not_depend_on_the_observed_target_or_confirmation():
    rows = [session(0, "a"), session(1, "b")]
    forecast = PredictionFeedback("wrong", START + timedelta(seconds=3), "a", "c", False,
                                  available_at=START + timedelta(seconds=4))
    example, = build_examples(rows, [forecast], NOW).examples
    assert example.feature_at == rows[0].at
    assert example.nxt == "b" and example.weight == 1


def test_conflicting_duplicate_outcome_identity_invalidates_both_occurrences():
    rows = [session(0, "a"), session(1, "b"), session(2, "other", source_id="1"), session(3, "d")]
    assert not build_examples(rows, [], NOW).examples


def test_late_feedback_cannot_change_historical_hour_or_day_features():
    source_at = datetime(2026, 10, 8, 23, 59, 55)
    rows = [session(0, "a", at=source_at, seconds=15),
            session(1, "b", at=source_at + timedelta(seconds=20))]
    forecast = PredictionFeedback("late", source_at + timedelta(seconds=10), "a", "b", True,
                                  available_at=NOW - timedelta(days=1))
    plain, = build_examples(rows, [], NOW).examples
    weighted, = build_examples(rows, [forecast], NOW).examples
    assert weighted.weight == 3
    assert weighted.feature_at == plain.feature_at == source_at


def test_append_same_app_chunk_keeps_transition_identity_and_first_settled_label():
    rows = [session(0, "a"), session(1, "b")]
    initial, = build_examples(rows, [], NOW).examples
    extended, = build_examples(rows + [session(2, "b")], [], NOW).examples
    assert extended.source_id == initial.source_id
    assert extended.label_at == initial.label_at == rows[1].at + timedelta(seconds=rows[1].seconds)
    assert extended.source_ids == ("0", "1", "2")
