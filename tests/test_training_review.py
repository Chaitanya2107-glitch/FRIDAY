import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.mind.reviews import ReviewStore


def test_capture_review_train_are_separate_and_persistent(tmp_path):
    store = ReviewStore(tmp_path / "reviews.db")
    item = store.capture("question", "Why gaming now?", {"pattern": "study>gaming", "where": "notice_jump"})
    assert store.get(item)["state"] == "pending"
    assert store.learned() == []
    with pytest.raises(ValueError, match="approved"):
        store.train(item)
    store.review(item, answer="I finished studying", teaching="Gaming follows completed study.", approve=True)
    assert store.learned() == []
    store.train(item)
    assert ReviewStore(store.path).learned()[0]["teaching"] == "Gaming follows completed study."
    store.train(item)  # Applying twice produces one lesson.
    assert len(store.learned()) == 1
    store.review(item, approve=False)
    assert store.learned() == []


def test_live_answer_is_evidence_not_approval(tmp_path):
    store = ReviewStore(tmp_path / "reviews.db")
    item = store.capture("question", "What are we doing?", {})
    store.answer(item, "Working", "answered")
    row = store.get(item)
    assert row["live_answer"] == "Working"
    assert row["state"] == "pending"
    assert store.learned() == []


def test_export_requires_explicit_consent_and_excludes_raw_context(tmp_path):
    store = ReviewStore(tmp_path / "reviews.db")
    item = store.capture("question", "What is that app?", {"its_window": "private window title"})
    store.review(item, answer="My editor", teaching="The app is my editor.", approve=True)
    target = tmp_path / "dataset.jsonl"
    assert store.export(target) == 0
    store.review(item, answer="My editor", teaching="The app is my editor.", approve=True, exportable=True)
    assert store.export(target) == 1
    data = target.read_text(encoding="utf-8")
    assert "private window title" not in data
    assert json.loads(data)["messages"][-1] == {"role": "assistant", "content": "The app is my editor."}
    with pytest.raises(FileExistsError):
        store.export(target)


def test_separate_connections_can_capture_while_reviewing(tmp_path):
    path = tmp_path / "reviews.db"
    store = ReviewStore(path)
    first = store.capture("question", "First?", {})
    def capture(i):
        return ReviewStore(path).capture("nudge", f"Nudge {i}", {})
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(capture, range(16)))
        store.review(first, teaching="A reviewed fact.", approve=True)
        store.train(first)
    assert len(set(ids)) == 16
    assert len(store.list("all")) == 17


def test_secrets_redacted_from_capture_and_review(tmp_path, monkeypatch):
    from core.config import config
    monkeypatch.setattr(config, "OPENAI_API_KEY", "secret-for-review-test")
    store = ReviewStore(tmp_path / "reviews.db")
    item = store.capture("question", "secret-for-review-test?", {"clipboard": "clipboard content", "at": "secret-for-review-test"})
    store.review(item, teaching="secret-for-review-test", approve=True)
    encoded = json.dumps(store.get(item))
    assert "secret-for-review-test" not in encoded
    assert "clipboard content" not in encoded


def test_blank_lessons_cannot_be_approved(tmp_path):
    store = ReviewStore(tmp_path / "reviews.db")
    item = store.capture("question", "Why?", {})
    with pytest.raises(ValueError):
        store.review(item, approve=True)
    assert store.get(item)["state"] == "pending"


def test_live_questions_keep_pending_state_and_capture_answers(monkeypatch):
    from services.mind import talk
    from services.mind.reviews import reviews
    monkeypatch.setattr(talk, "_learn_answer", lambda *a: None)
    talk._record({"say": "What are we doing?", "raw": {"kind": "start"}}, "start", 10)
    pending = talk.load()["pending"]
    item = reviews.list()[0]
    assert item["context"]["where"] == "start"
    reviews.review(item["id"], teaching="I work on FRIDAY.", approve=True)
    reviews.train(item["id"])
    assert talk.load()["pending"] == pending
    assert talk.hear("Working on FRIDAY", now=pending["at"] + 1) == "answered"
    assert reviews.get(item["id"])["live_answer"] == "Working on FRIDAY"


def test_unreviewed_context_stays_out_of_shared_prompt_and_reason():
    from core.config import config
    from services.mind import thoughts
    from services.mind.reviews import reviews
    item = reviews.capture("question", "PRIVATE QUESTION", {"pattern": "study>gaming", "its_window": "PRIVATE WINDOW"})
    assert "PRIVATE QUESTION" not in config.SYSTEM_PROMPT
    assert "PRIVATE WINDOW" not in config.SYSTEM_PROMPT
    reviews.review(item, teaching="I completed my studying.", approve=True)
    assert thoughts.reason_for("study>gaming") is None
    reviews.train(item)
    assert thoughts.reason_for("study>gaming") == "I completed my studying."
    assert "I completed my studying." in config.SYSTEM_PROMPT
    assert "PRIVATE WINDOW" not in config.SYSTEM_PROMPT
    reviews.reject(item)
    assert thoughts.reason_for("study>gaming") is None
    assert "I completed my studying." not in config.SYSTEM_PROMPT


def test_capture_failure_does_not_break_live_question(monkeypatch):
    from services.mind import talk
    from services.mind.reviews import reviews
    def failed(*a, **kw):
        raise OSError("Cannot write")
    monkeypatch.setattr(reviews, "capture", failed)
    talk._record({"say": "Still asking", "raw": {}}, "start", 100)
    assert talk.load()["pending"]["question"] == "Still asking"


def test_nudge_delivery_still_runs_and_is_recorded(monkeypatch):
    from services.mind import training
    from services.mind.reviews import reviews
    from services.reminders import service
    called = []
    monkeypatch.setattr(service, "show_toast", lambda *a, **kw: called.append(a) or True)
    assert training.show_toast("FRIDAY", "Eye break time") is True
    row = reviews.list()[0]
    assert row["kind"] == "nudge"
    assert row["question"] == "Eye break time"
    assert row["delivery"] == "submitted"
    assert called == [("FRIDAY", "Eye break time")]


def test_manual_cli_flow_and_withdrawal(tmp_path, capsys):
    import train_friday
    from services.mind.reviews import reviews
    assert train_friday.main(["add", "--question", "What can you send via Telegram?", "--response", "Messages and files."]) == 0
    item = reviews.list()[0]
    assert item["state"] == "pending"
    assert train_friday.main(["train", "--id", str(item["id"])]) == 1
    assert train_friday.main(["approve", str(item["id"]), "--exportable"]) == 0
    assert reviews.learned() == []
    assert train_friday.main(["train", "--all-approved"]) == 0
    assert len(reviews.learned()) == 1
    target = tmp_path / "dataset.jsonl"
    assert train_friday.main(["export", str(target)]) == 0
    assert json.loads(target.read_text())["messages"] == [
        {"role": "user", "content": "What can you send via Telegram?"},
        {"role": "assistant", "content": "Messages and files."}]
    assert train_friday.main(["withdraw", str(item["id"])]) == 0
    assert reviews.learned() == []
    assert reviews.get(item["id"])["preferred"] == "Messages and files."


def test_interactive_review_requires_approval_and_apply(monkeypatch):
    import train_friday
    from services.mind.reviews import reviews
    item = reviews.capture("question", "What is this?", {})
    answers = iter(["My editor", "This is my code editor.", "", "Checked it", "y", "n", "n"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    train_friday.review(item)
    assert reviews.get(item)["state"] == "approved"
    assert reviews.learned() == []
    assert not reviews.get(item)["exportable"]


def test_training_new_app_description_is_reversible():
    from datetime import datetime
    from services.mind import knowledge
    from services.mind.reviews import reviews
    with knowledge.db() as conn:
        knowledge.see(conn, "app", "unknowneditor", "other", datetime.now())
    item = reviews.capture("question", "What is unknowneditor?", {"subject": "app:unknowneditor"})
    reviews.review(item, teaching="My offline code editor.", approve=True)
    reviews.train(item)
    assert knowledge.get("app:unknowneditor").about == "My offline code editor."
    assert knowledge.find("unknowneditor").about == "My offline code editor."
    reviews.reject(item)
    assert knowledge.get("app:unknowneditor").about is None


def test_review_and_dataset_do_not_make_network_calls(monkeypatch, tmp_path):
    import httpx
    import train_friday
    def forbidden(*a, **kw):
        pytest.fail("Training tool tried a network call")
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    assert train_friday.main(["add", "--question", "Hello?", "--response", "Hi."]) == 0
    assert train_friday.main(["approve", "1", "--exportable"]) == 0
    assert train_friday.main(["train", "--id", "1"]) == 0
    assert train_friday.main(["export", str(tmp_path / "offline.jsonl")]) == 0
