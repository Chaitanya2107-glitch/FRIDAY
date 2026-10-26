"""
services/mind/learner.py

The self-training predictor. Every night it trains a small model (scikit-learn logistic regression)
on the Boss's app switches — from which app, the one before it, the hour, the weekday — and tests
it on the last TEST_DAYS days against the counting Predictor (services/activity/predict.py) trained
on the same earlier days. The model takes over "what will I open next" and the command bar's
app guesses only while it beats the counting predictor; otherwise counting stays in charge.
Nothing is shown on its own. All local.

Whether or not it wins, the latest model is also kept as a second opinion (next_app_shadow.pkl): her
brain compares its guess with her own counting at every switch (services/mind/foresight.py), and the
predictions the Boss confirmed there count extra in the training.

With LEARNING_DATA_ENABLED, the catalog supplies screened, attributable observed transitions.
Outcome availability determines the chronological split; confirmation evidence supplies explicit
weights only when already available. The deployed model is the candidate actually evaluated,
and policy/artifact manifests prevent legacy models from bypassing the data gate. Disabling the
switch retains the historical pathway above.

State: memory/mind/next_app.pkl (the champion, only while it wins), next_app_shadow.pkl (the latest
model, always) and memory/mind/learner.json (the latest scores, for "what's on your mind").
"""

import json
import pickle
import hashlib
from uuid import uuid4
from datetime import datetime, timedelta

from core.config import config
from core.logger import logger
from services.activity.predict import TOP, Predictor, switches

model_path = config.MEMORY_DIR / "mind" / "next_app.pkl"  # tests point these elsewhere
shadow_path = config.MEMORY_DIR / "mind" / "next_app_shadow.pkl"
scores_path = config.MEMORY_DIR / "mind" / "learner.json"
TEST_DAYS = 3
MIN_TEST = 100   # fewer test switches than this: no verdict
MIN_TRAIN = 300
MARGIN = 0.02    # must win top-3 by 2 points (and not lose top-1) to take over

_loaded: dict = {}  # file → (loaded model, mtime), reloaded when the file changes


def features(app: str, before: str | None, when: datetime) -> dict:
    return {f"from={app}": 1, f"before={before or '-'}": 1, f"hour={when.hour}": 1, f"from_hour={app}@{when.hour}": 1,
            f"weekend={when.weekday() >= 5}": 1, f"day={when.weekday()}": 1}


def _fit(rows: list[tuple[datetime, str, str, str | None]], sample_weight=None):
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    model = make_pipeline(DictVectorizer(), LogisticRegression(max_iter=500, C=0.5, random_state=0))
    options = {"logisticregression__sample_weight": sample_weight} if sample_weight is not None else {}
    model.fit([features(app, before, when) for when, app, _, before in rows], [nxt for _, _, nxt, _ in rows], **options)
    return model


def _model_top(model, app: str, before: str | None, when: datetime, n: int = TOP) -> list[str]:
    probs = model.predict_proba([features(app, before, when)])[0]
    ranked = [label for _, label in sorted(zip(probs, model.classes_), reverse=True) if label != app]
    return ranked[:n]


def _score(guess, test) -> dict:
    top1 = top3 = 0
    for when, app, nxt, before in test:
        guesses = guess(app, before, when)
        top1 += bool(guesses) and guesses[0] == nxt
        top3 += nxt in guesses
    return {"top1": round(top1 / len(test), 3), "top3": round(top3 / len(test), 3)}


def train(log, now: datetime | None = None) -> dict | None:
    """Nightly: train, test against counting, promote or retire the model. Returns the scores, or None (too little data)."""
    now = now or datetime.now()
    if getattr(config, "LEARNING_DATA_ENABLED", False):
        return _train_clean(log, now)
    rows = switches(log.app_sequence())
    cut = now - timedelta(days=TEST_DAYS)
    earlier, test = [r for r in rows if r[0] < cut], [r for r in rows if r[0] >= cut]
    if len(earlier) < MIN_TRAIN or len(test) < MIN_TEST:
        return None
    counting = Predictor()
    for when, app, nxt, before in earlier:
        counting.learn(app, nxt, when, before)
    challenger = _fit(earlier)
    old = _score(lambda a, b, w: counting.top(a, w, b), test)
    new = _score(lambda a, b, w: _model_top(challenger, a, b, w), test)
    wins = new["top3"] >= old["top3"] + MARGIN and new["top1"] >= old["top1"]
    from services.mind import foresight  # it builds on this module: import late

    model_path.parent.mkdir(parents=True, exist_ok=True)
    latest = pickle.dumps(_fit(rows + foresight.verified_rows()))  # everything, test days and confirmed guesses included
    shadow_path.write_bytes(latest)
    if wins:
        model_path.write_bytes(latest)
    else:
        model_path.unlink(missing_ok=True)
    result = {"day": now.date().isoformat(), "model": new, "counting": old, "in_charge": "model" if wins else "counting",
              "tested_on": len(test), "trained_on": len(earlier)}
    scores_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    logger.info(f"Learner: model {new} vs counting {old} on {len(test)} switches — {result['in_charge']} in charge")
    return result


def _manifest_path(path):
    return path.with_suffix(".manifest.json")


def _artifact_manifest(path):
    """Only audited artifacts with matching bytes and policy may remain active."""
    from services.learning.contracts import POLICY_VERSION
    try:
        manifest = json.loads(_manifest_path(path).read_text(encoding="utf-8"))
        if (isinstance(manifest, dict) and manifest.get("policy_version") == POLICY_VERSION
                and manifest.get("status") == "completed"
                and manifest.get("artifact_sha256") == hashlib.sha256(path.read_bytes()).hexdigest()):
            return manifest
    except (OSError, ValueError):
        pass
    return None


def _retire_models():
    for path in (model_path, shadow_path):
        path.unlink(missing_ok=True)
        _manifest_path(path).unlink(missing_ok=True)
        _loaded.pop(path, None)


def _train_clean(log, now: datetime) -> dict:
    """Fit and publish one audited candidate, using observed outcome availability."""
    from services.learning import service
    from services.learning.catalog import catalog
    from services.activity.predict import BACK, _slot

    dataset = service.refresh(log=log, now=now)
    cut = now - timedelta(days=TEST_DAYS)
    earlier = [e for e in dataset.examples if e.label_at < cut]
    test = [e for e in dataset.examples if cut <= e.feature_at and e.label_at <= now]
    crossing = [e for e in dataset.examples if e.feature_at < cut <= e.label_at]
    result = {"id": str(uuid4()), "at": now.isoformat(), "day": now.date().isoformat(),
              "status": "skipped", "reason": "", "dataset_version": dataset.fingerprint,
              "policy_version": dataset.policy_version, "cutoff": cut.isoformat(),
              "training_ids": [], "evaluation_ids": [], "model": None, "counting": None,
              "in_charge": "counting", "trained_on": 0, "tested_on": 0,
              "eligible": len(dataset.examples), "available_train": len(earlier), "available_test": len(test),
              "purged_crossing_examples": len(crossing)}
    unavailable = bool(dataset.reasons.get("source_unavailable"))
    reason = ("source_unavailable" if unavailable else
              "insufficient_training_examples" if len(earlier) < MIN_TRAIN else
              "insufficient_evaluation_examples" if len(test) < MIN_TEST else
              "insufficient_target_classes" if len({e.nxt for e in earlier}) < 2 else "")
    if not reason:
        rows = [e.row for e in earlier]
        weights = [e.weight if e.feedback_at is not None and e.feedback_at < cut else 1.0 for e in earlier]
        counting = Predictor()
        for example, weight in zip(earlier, weights):
            counting.learn(example.app, example.nxt, example.feature_at, example.before)
            target = BACK if example.nxt == example.before else example.nxt
            for counts in (counting.after[example.app], counting.after_at_hour[(example.app, example.feature_at.hour)],
                           counting.at_slot[_slot(example.feature_at)]):
                counts[target] += weight - 1
        try:
            challenger = _fit(rows, sample_weight=weights)
            result.update(training_ids=[e.source_id for e in earlier], trained_on=len(earlier),
                          weights=dict(zip((e.source_id for e in earlier), weights)),
                          source_ids={e.source_id: list(e.source_ids) for e in earlier},
                          feedback_ids={e.source_id: list(e.feedback_ids) for e, weight in zip(earlier, weights) if weight > 1})
            test_rows = [e.row for e in test]
            old = _score(lambda a, b, w: counting.top(a, w, b), test_rows)
            new = _score(lambda a, b, w: _model_top(challenger, a, b, w), test_rows)
            latest = pickle.dumps(challenger)
        except Exception as error:
            logger.warning(f"Clean learner fitting failed: {type(error).__name__}")
            reason = "fitting_failed"
        else:
            wins = new["top3"] >= old["top3"] + MARGIN and new["top1"] >= old["top1"]
            result.update(status="completed", training_ids=[e.source_id for e in earlier],
                          evaluation_ids=[e.source_id for e in test], model=new, counting=old,
                          in_charge="model" if wins else "counting", trained_on=len(earlier), tested_on=len(test),
                          weights=dict(zip((e.source_id for e in earlier), weights)))
            result["source_ids"].update({e.source_id: list(e.source_ids) for e in test})
            manifest = {**result, "artifact_sha256": hashlib.sha256(latest).hexdigest()}
            model_path.parent.mkdir(parents=True, exist_ok=True)
            shadow_path.write_bytes(latest)
            _manifest_path(shadow_path).write_text(json.dumps(manifest), encoding="utf-8")
            if wins:
                model_path.write_bytes(latest)
                _manifest_path(model_path).write_text(json.dumps(manifest), encoding="utf-8")
            else:
                model_path.unlink(missing_ok=True)
                _manifest_path(model_path).unlink(missing_ok=True)
            _loaded.clear()
    if reason:
        result["reason"] = reason
        if unavailable:
            # A failed scan provides no new eligibility verdict. Do not fit stale
            # rows or erase a previously evaluated compatible predictor.
            manifest = _artifact_manifest(model_path)
            result.update(eligible=None, in_charge="model" if manifest else "counting",
                          preserved_artifact=bool(manifest))
            if manifest:
                result.update(model=manifest.get("model"), counting=manifest.get("counting"))
        else:
            _retire_models()
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    scores_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    catalog.record_training_run(result)
    logger.info(f"Clean learner: {result['status']} ({reason or result['in_charge']}); "
                f"{len(dataset.examples)} eligible, {len(earlier)} earlier, {len(test)} held out")
    return result


def top(app: str, before: str | None, when: datetime, n: int = TOP) -> list[str] | None:
    """The champion model's guesses, or None when counting is in charge (or anything goes wrong)."""
    return _ask(model_path, app, before, when, n)


def guess(app: str, before: str | None, when: datetime) -> str | None:
    """The latest trained model's first guess, in charge or not; None until it has been trained."""
    return (guesses(app, before, when, 1) or [None])[0]


def guesses(app: str, before: str | None, when: datetime, n: int = TOP) -> list[str] | None:
    """The latest trained model's top guesses, in charge or not; None until it has been trained."""
    return _ask(shadow_path, app, before, when, n)


def _ask(path, app: str, before: str | None, when: datetime, n: int) -> list[str] | None:
    try:
        if getattr(config, "LEARNING_DATA_ENABLED", False):
            if _artifact_manifest(path) is None:
                return None
        mtime = path.stat().st_mtime
    except (OSError, ValueError):
        return None
    try:
        if path not in _loaded or _loaded[path][1] != mtime:
            _loaded[path] = (pickle.loads(path.read_bytes()), mtime)  # our own file, written by train()
        return _model_top(_loaded[path][0], app, before, when, n)
    except Exception as e:  # a guess must never break anything
        logger.info(f"Learner model unusable: {e}")
        return None


def summary() -> str:
    try:
        s = json.loads(scores_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "My self-trained predictor hasn't had enough days of data to test itself yet."
    if s.get("status") == "skipped":
        if s.get("reason") == "source_unavailable":
            who = "the previous evaluated model remains in charge" if s.get("in_charge") == "model" else "counting remains in charge"
            return f"Clean next-app training skipped: source data unavailable. No new data was fitted; {who}."
        reasons = {"insufficient_training_examples": "fewer than 300 earlier eligible examples",
                   "insufficient_evaluation_examples": "fewer than 100 held-out eligible examples",
                   "insufficient_target_classes": "fewer than two observed target apps",
                   "fitting_failed": "the fitting run failed"}
        reason = reasons.get(s.get("reason"), "the clean-data checks were not satisfied")
        return (f"Clean next-app training skipped: {reason}. {s.get('eligible', 0)} eligible examples; "
                "counting remains in charge.")
    pct = lambda x: f"{round(100 * x)}%"
    who = "the trained model is in charge" if s["in_charge"] == "model" else "simple counting still wins, so it stays in charge"
    return (f"Next-app guessing, tested {s['day']} on {s['tested_on']} switches: trained model {pct(s['model']['top3'])} "
            f"in the top 3 vs counting {pct(s['counting']['top3'])} — {who}.")
