import json
import pickle
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.learning.contracts import Dataset, TrainingExample
from services.learning import service
from services.learning.catalog import catalog
from services.mind import learner

NOW = datetime(2026, 10, 12, 12)
CUT = NOW - timedelta(days=learner.TEST_DAYS)


def example(i, feature_at, label_at, **changes):
    return replace(TrainingExample(str(i), feature_at, label_at, "a", "b" if i % 2 else "c",
                                   None, (f"s{i}", f"t{i}")), **changes)


@pytest.fixture
def clean(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_DATA_ENABLED", True, raising=False)
    runs = []
    monkeypatch.setattr(catalog, "record_training_run", runs.append)
    learner._loaded.clear()
    return runs


def setup_dataset(monkeypatch, rows):
    monkeypatch.setattr(service, "refresh", lambda **kwargs: Dataset(tuple(rows), "snapshot"))


def test_insufficient_clean_data_retires_legacy_models_and_records_skip(clean, monkeypatch):
    setup_dataset(monkeypatch, [])
    learner.model_path.parent.mkdir(parents=True, exist_ok=True)
    learner.model_path.write_bytes(pickle.dumps("legacy"))
    learner.shadow_path.write_bytes(pickle.dumps("legacy"))
    result = learner.train(object(), NOW)
    assert result["status"] == "skipped" and result["reason"] == "insufficient_training_examples"
    assert not learner.model_path.exists() and not learner.shadow_path.exists()
    assert clean[0]["training_ids"] == []
    assert "clean" in learner.summary().lower()


def test_legacy_artifact_cannot_predict_in_clean_mode(clean):
    learner.model_path.parent.mkdir(parents=True, exist_ok=True)
    learner.model_path.write_bytes(pickle.dumps("legacy"))
    assert learner.top("a", None, NOW) is None


def test_chronological_outcome_cut_and_future_feedback_weights(clean, monkeypatch):
    rows = [example(i, CUT - timedelta(hours=2), CUT - timedelta(hours=1),
                    weight=3, feedback_at=CUT + timedelta(minutes=1)) for i in range(learner.MIN_TRAIN)]
    rows += [example(500+i, CUT, CUT + timedelta(seconds=5))
             for i in range(learner.MIN_TEST)]
    rows.append(example(999, CUT - timedelta(seconds=5), CUT + timedelta(seconds=5)))
    setup_dataset(monkeypatch, rows)
    fitted = []
    def fit(data, sample_weight=None):
        fitted.append((data, sample_weight))
        return {"evaluated": True}
    monkeypatch.setattr(learner, "_fit", fit)
    scores = iter([{"top1": .2, "top3": .4}, {"top1": .3, "top3": .5}])
    monkeypatch.setattr(learner, "_score", lambda guess, data: next(scores))
    result = learner.train(object(), NOW)
    assert result["trained_on"] == learner.MIN_TRAIN and result["tested_on"] == learner.MIN_TEST
    assert result["purged_crossing_examples"] == 1
    assert "999" not in result["training_ids"] + result["evaluation_ids"]
    assert len(fitted) == 1
    assert fitted[0][1] == [1.0] * learner.MIN_TRAIN
    assert all(r[0] < CUT for r in fitted[0][0])
    assert pickle.loads(learner.model_path.read_bytes()) == {"evaluated": True}
    assert learner.shadow_path.read_bytes() == learner.model_path.read_bytes()
    assert len(clean[0]["training_ids"]) == learner.MIN_TRAIN
    assert len(clean[0]["evaluation_ids"]) == learner.MIN_TEST
    manifest = json.loads(learner.model_path.with_suffix(".manifest.json").read_text())
    assert manifest["dataset_version"] == "snapshot"


def test_single_target_class_skips_with_clear_reason(clean, monkeypatch):
    rows = [example(i, CUT - timedelta(hours=2), CUT - timedelta(hours=1), nxt="b")
            for i in range(learner.MIN_TRAIN)]
    rows += [example(500+i, CUT, CUT + timedelta(hours=1)) for i in range(learner.MIN_TEST)]
    setup_dataset(monkeypatch, rows)
    result = learner.train(object(), NOW)
    assert result["reason"] == "insufficient_target_classes"


@pytest.mark.parametrize("new", [{"top1": .19, "top3": .8}, {"top1": .3, "top3": .41}])
def test_promotion_requires_margin_and_no_top_one_regression(clean, monkeypatch, new):
    rows = [example(i, CUT - timedelta(hours=2), CUT - timedelta(hours=1)) for i in range(learner.MIN_TRAIN)]
    rows += [example(500+i, CUT, CUT + timedelta(hours=1)) for i in range(learner.MIN_TEST)]
    setup_dataset(monkeypatch, rows)
    monkeypatch.setattr(learner, "_fit", lambda *a, **kw: {"candidate": True})
    scores = iter([{"top1": .2, "top3": .4}, new])
    monkeypatch.setattr(learner, "_score", lambda *a: next(scores))
    assert learner.train(object(), NOW)["in_charge"] == "counting"
    assert not learner.model_path.exists() and learner.shadow_path.exists()


def test_known_feedback_weights_fit_and_baseline_once_per_example(clean, monkeypatch):
    rows = [example(i, CUT - timedelta(hours=2), CUT - timedelta(hours=1),
                    weight=3, feedback_at=CUT - timedelta(minutes=1), feedback_ids=("f",))
            for i in range(learner.MIN_TRAIN)]
    rows += [example(500+i, CUT, CUT + timedelta(hours=1)) for i in range(learner.MIN_TEST)]
    setup_dataset(monkeypatch, rows)
    weights_seen = []
    monkeypatch.setattr(learner, "_fit", lambda data, sample_weight: weights_seen.extend(sample_weight) or {})
    counts_seen = []
    original_learn = learner.Predictor.learn
    def learn(self, app, nxt, when, before):
        counts_seen.append(self)
        original_learn(self, app, nxt, when, before)
    monkeypatch.setattr(learner.Predictor, "learn", learn)
    monkeypatch.setattr(learner, "_score", lambda *a: {"top1": .2, "top3": .4})
    result = learner.train(object(), NOW)
    assert weights_seen == [3] * learner.MIN_TRAIN
    assert sum(counts_seen[0].after["a"].values()) == 3 * learner.MIN_TRAIN
    assert len(result["training_ids"]) == learner.MIN_TRAIN


def test_fit_failure_is_a_reported_skip_with_counting_available(clean, monkeypatch):
    rows = [example(i, CUT - timedelta(hours=2), CUT - timedelta(hours=1)) for i in range(learner.MIN_TRAIN)]
    rows += [example(500+i, CUT, CUT + timedelta(hours=1)) for i in range(learner.MIN_TEST)]
    setup_dataset(monkeypatch, rows)
    def fail(*args, **kwargs):
        raise ValueError("broken candidate")
    monkeypatch.setattr(learner, "_fit", fail)
    result = learner.train(object(), NOW)
    assert result["reason"] == "fitting_failed" and result["training_ids"] == []
    assert learner.top("a", None, NOW) is None


def test_unavailable_source_preserves_valid_artifacts_and_reports_read_failure(clean, monkeypatch):
    candidate = pickle.dumps({"tested": True})
    learner.model_path.parent.mkdir(parents=True, exist_ok=True)
    for path in (learner.model_path, learner.shadow_path):
        path.write_bytes(candidate)
        path.with_suffix(".manifest.json").write_text(json.dumps({
            "policy_version": "next-app-v1", "status": "completed", "dataset_version": "previous",
            "artifact_sha256": hashlib.sha256(candidate).hexdigest(), "in_charge": "model"}))
    monkeypatch.setattr(service, "refresh", lambda **kwargs: Dataset((), "source-unavailable", {"source_unavailable": 1}))
    monkeypatch.setattr(learner, "_fit", lambda *args, **kwargs: pytest.fail("unavailable source must not fit"))
    result = learner.train(object(), NOW)
    assert result["reason"] == "source_unavailable" and result["status"] == "skipped"
    assert result["training_ids"] == [] and result["evaluation_ids"] == []
    assert result["in_charge"] == "model"
    assert learner.model_path.read_bytes() == learner.shadow_path.read_bytes() == candidate
    assert "unavailable" in learner.summary().lower()
