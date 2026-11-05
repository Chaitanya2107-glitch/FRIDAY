"""Train Friday now reviews predictions rather than conducting interviews."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

import train_friday
from services.activity import predict
from services.mind import brain, foresight, knowledge, prediction_review as review, talk, thoughts
from services.mind.reviews import reviews

NOW = datetime(2026, 10, 30, 15)


def prediction(*, kind="prediction", target="app:spotify", when=NOW, source="code"):
    return thoughts.add(kind, f"next:{source}>{target}:{when.isoformat()}", {
        "program": target.split(":", 1)[1], "after": source, "because": "a recorded pattern",
        "context": {"pattern": f"{source}>{target}", "frm": source, "thing": target,
                    "before": "chrome", "at": when.isoformat()}}, 0.6, when)


def test_queue_only_contains_saved_predictions_and_shows_evidence(capsys):
    item = prediction()
    prediction(kind="automate")
    thoughts.add("unknown", "app:editor", {"name": "editor"}, 0.8, NOW)
    reviews.capture("example", "Manual example", {})
    assert [row["id"] for row in review.queue()] == [item]
    assert train_friday.main(["list"]) == 0
    output = capsys.readouterr().out
    assert "spotify" in output and "2026-10-30" in output and "recorded pattern" in output
    assert "Manual example" not in output


def test_verification_automatically_teaches_without_approval_or_train():
    item = prediction()
    assert train_friday.main(["review", str(item), "--verdict", "correct"]) == 0
    assert not review.queue()
    assert review.get(item)["verdict"] == "correct"
    assert len(foresight.verified_rows()) == foresight.VERIFIED_WEIGHT
    assert not reviews.learned()
    with knowledge.db() as conn:
        row = conn.execute("SELECT * FROM foresight_patterns").fetchone()
    assert row["yes"] == 1 and row["auto"] == 0


def test_negative_feedback_and_correction_change_future_guesses():
    item = prediction()
    review.verify(item, "wrong", actual_app="WhAtSaPp.exe", notes="I opened chat", now=NOW)
    assert review.rank(["spotify", "whatsapp.root"], "code", "chrome", NOW) == ["whatsapp.root", "spotify"]
    assert review.rank(["spotify"], "code", "chrome", NOW)[0] == "whatsapp.root"
    assert foresight.verified_rows()[0][2] == "whatsapp.root"
    assert review.get(item)["actual_app"] == "whatsapp.root"
    with knowledge.db() as conn:
        assert [tuple(row) for row in conn.execute("SELECT nxt,right FROM foresight_labels")] == [
            ("spotify", 0), ("whatsapp.root", 1)]


def test_wrong_without_actual_app_never_trains_a_positive_example():
    review.verify(prediction(), "wrong", now=NOW)
    assert not foresight.verified_rows()
    assert review.rank(["spotify", "whatsapp.root"], "code", "chrome", NOW)[0] == "whatsapp.root"


@pytest.mark.parametrize("verdict", ["unsure", "garbage"])
def test_nondefinite_input_never_consumes_prediction(verdict):
    item = prediction()
    if verdict == "unsure":
        assert review.verify(item, verdict) is False
    else:
        with pytest.raises(ValueError):
            review.verify(item, verdict)
    assert review.queue()[0]["id"] == item
    assert not foresight.verified_rows()


@pytest.mark.parametrize("kind", ["automate", "unknown", "new"])
def test_nonprediction_ids_are_refused(kind):
    item = prediction(kind=kind)
    with pytest.raises(ValueError, match="does not exist"):
        review.verify(item, "correct")
    assert thoughts.get(item)


@pytest.mark.parametrize("verdict,actual", [("correct", "whatsapp.root"), ("wrong", "spotify"),
                                         ("wrong", "../bad"), ("unsure", "whatsapp.root"),
                                         ("wrong", "VS Code"), ("wrong", "code.exe")])
def test_invalid_corrections_do_not_partially_train(verdict, actual):
    item = prediction()
    with pytest.raises(ValueError):
        review.verify(item, verdict, actual_app=actual)
    assert review.queue()[0]["id"] == item
    with knowledge.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM foresight_labels").fetchone()[0] == 0


def test_known_display_name_corrections_use_observed_app_identities():
    item = prediction(source="chrome")
    review.verify(item, "wrong", actual_app="VS Code", now=NOW)
    assert review.get(item)["actual_app"] == "code"
    assert foresight.verified_rows()[0][2] == "code"


def test_duplicate_verification_is_atomic_across_connections():
    item = prediction()
    def verify():
        try:
            return review.verify(item, "correct", now=NOW)
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: verify(), range(2))) == 1
    assert len(foresight.verified_rows()) == foresight.VERIFIED_WEIGHT
    with knowledge.db() as conn:
        assert conn.execute("SELECT yes FROM foresight_patterns").fetchone()[0] == 1


def test_live_and_manual_verification_share_deduplication():
    item = prediction()
    brain.answered(item, "yes", NOW)
    brain.answered(item, "yes", NOW)
    assert len(foresight.verified_rows()) == foresight.VERIFIED_WEIGHT
    assert train_friday.main(["review", str(item), "--verdict", "correct"]) == 1


@pytest.mark.parametrize("answer", ["hmm", "not sure", "I don't know", "maybe", "I'm unsure"])
def test_live_uncertain_reply_can_still_be_reviewed(answer):
    item = prediction()
    brain.answered(item, answer, NOW)
    assert review.queue()[0]["id"] == item
    review.verify(item, "correct")


def test_session_skips_and_stops_without_consuming_live_pending(monkeypatch):
    first = prediction()
    second = prediction(when=NOW + timedelta(minutes=1))
    pending = {"question": "Live question", "thought": first, "at": 1}
    talk._save({"pending": pending})
    answers = iter(["", "/stop"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert train_friday.main(["session"]) == 0
    assert len(review.queue()) == 2
    assert talk.load()["pending"] == pending
    assert {row["id"] for row in review.queue()} == {first, second}


def test_session_saves_each_verification_before_interrupt(monkeypatch):
    prediction()
    latest = prediction(when=NOW + timedelta(minutes=1))
    answers = iter(["c"])
    def answer(*args):
        try:
            return next(answers)
        except StopIteration:
            raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", answer)
    assert train_friday.main(["session"]) == 0
    assert review.get(latest)["verdict"] == "correct"
    assert len(review.queue()) == 1


def test_uncounted_correction_reaches_shared_predictor_and_foresight(monkeypatch):
    review.verify(prediction(), "wrong", actual_app="whatsapp.root", now=NOW)
    monkeypatch.setattr("services.mind.learner.top", lambda *a: ["spotify"])
    assert predict._guesses(predict.Predictor(), "code", "chrome", NOW)[0] == "whatsapp.root"
    assert foresight.final({"app": "code", "before": "chrome", "own": "spotify", "model": None}, NOW) == "whatsapp.root"


def test_correction_is_not_misattributed_to_a_trained_model():
    from types import SimpleNamespace
    review.verify(prediction(), "wrong", actual_app="whatsapp.root", now=NOW)
    counts = predict.Predictor()
    counts.learn("code", "spotify", NOW, "chrome")
    foresight._counts = counts, NOW
    foresight._pending = {"app": "code", "before": "chrome", "at": NOW - timedelta(minutes=1),
                          "own": "spotify", "model": None}
    result = foresight._next_app(SimpleNamespace(app="code"), NOW, False)
    assert result[0][2]["program"] == "WhatsApp"
    assert "verification" in result[0][2]["because"]
    assert "trained model says" not in result[0][2]["because"]


def test_feedback_is_scoped_and_never_used_before_prediction_time():
    review.verify(prediction(), "wrong", actual_app="whatsapp.root", now=NOW)
    assert review.rank(["spotify"], "code", "chrome", NOW - timedelta(days=1)) == ["spotify"]
    assert review.rank(["spotify"], "code", "other", NOW) == ["spotify"]
    assert review.rank(["spotify"], "code", "chrome", NOW + timedelta(hours=1)) == ["spotify"]
    assert review.rank(["spotify"], "other", "chrome", NOW) == ["spotify"]


def test_late_feedback_is_not_used_before_it_was_available():
    review.verify(prediction(), "wrong", actual_app="whatsapp.root", now=NOW + timedelta(days=1))
    assert review.rank(["spotify"], "code", "chrome", NOW) == ["spotify"]


def test_duplicate_from_tool_then_live_reply_is_not_counted_twice():
    item = prediction()
    review.verify(item, "correct", now=NOW)
    brain.answered(item, "no", NOW)
    with knowledge.db() as conn:
        row = conn.execute("SELECT yes,no,auto FROM foresight_patterns").fetchone()
        assert tuple(row) == (1, 0, 0)


def test_failed_label_write_rolls_back_verification():
    item = prediction()
    with knowledge.db() as conn:
        conn.execute("CREATE TRIGGER fail_label BEFORE INSERT ON foresight_labels BEGIN SELECT RAISE(ABORT,'test'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        review.verify(item, "correct")
    assert review.queue()[0]["id"] == item
    assert review.get(item)["verdict"] is None
    with knowledge.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM foresight_patterns").fetchone()[0] == 0


@pytest.mark.parametrize("target", ["site:github.com", "project:friday"])
def test_nonapp_prediction_updates_belief_without_app_labels(target):
    item = prediction(target=target)
    review.verify(item, "correct")
    assert review.get(item)["verdict"] == "correct"
    assert not foresight.verified_rows()


def test_time_habit_without_a_source_app_can_still_be_verified():
    item = prediction(source=None)
    review.verify(item, "correct")
    assert review.get(item)["verdict"] == "correct"
    assert not foresight.verified_rows()


def test_bad_historical_labels_do_not_break_predictions():
    with knowledge.db() as conn:
        conn.execute("INSERT INTO foresight_labels (at,frm,before,nxt,right,recorded_at) VALUES (?,?,?,?,?,?)",
                     ("broken", "code", "chrome", "spotify", 1, "broken"))
    assert review.rank(["spotify"], "code", "chrome", NOW) == ["spotify"]


def test_persistence_and_old_answered_predictions_are_not_reapplied():
    item = prediction()
    thoughts.answered(item, "yes", NOW)
    assert not review.queue()
    assert review.queue("verified")[0]["id"] == item
    with pytest.raises(ValueError, match="already verified"):
        review.verify(item, "correct")
    other = prediction(when=NOW + timedelta(minutes=1))
    review.verify(other, "correct")
    knowledge._ready_for = None
    assert review.get(other)["verdict"] == "correct"


def test_tool_makes_no_network_calls(monkeypatch):
    import httpx
    def forbidden(*a, **kw):
        pytest.fail("Prediction review tried a network call")
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    item = prediction()
    assert train_friday.main(["show", str(item)]) == 0
    assert train_friday.main(["review", str(item), "--verdict", "wrong"]) == 0


def test_session_count_and_missing_predictions(capsys):
    assert train_friday.main(["session", "--count", "0"]) == 1
    assert train_friday.main(["show", "999"]) == 1
    assert train_friday.main(["list"]) == 0
    assert "No pending predictions" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["add", "approve", "train", "export", "questions", "feedback"])
def test_legacy_training_operations_are_unavailable(command):
    with pytest.raises(SystemExit) as error:
        train_friday.main([command])
    assert error.value.code == 2
