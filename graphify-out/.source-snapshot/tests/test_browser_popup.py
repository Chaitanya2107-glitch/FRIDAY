from interfaces.popup import automation


def test_progress_stops_at_the_reviewable_step(monkeypatch):
    statuses = iter([
        {"job_id": "one", "active": True, "response": "Reading", "awaiting_reply": False},
        {"job_id": "one", "active": True, "response": "Review this step", "awaiting_reply": True},
    ])
    monkeypatch.setattr(automation.backend, "automation_status", lambda: next(statuses))
    monkeypatch.setattr(automation.time, "sleep", lambda seconds: None)
    received = []
    automation.follow("browser task read a page", lambda *args: received.append(args), lambda: True, "one")
    assert received == [("Reading", False), ("Review this step", True)]


def test_late_status_never_replaces_a_new_command(monkeypatch):
    monkeypatch.setattr(automation.backend, "automation_status", lambda: {
        "job_id": "another", "active": True, "response": "Old progress", "awaiting_reply": False})
    received = []
    automation.follow("browser yes", lambda *args: received.append(args), lambda: True, "original")
    automation.follow("browser yes", lambda *args: received.append(args), lambda: False, "another")
    assert received == []


def test_old_backend_error_cannot_replace_a_new_response(monkeypatch):
    from interfaces.popup import app
    state = dict(app._state, request_generation=1, response="New reply", automation_polling=True)
    monkeypatch.setattr(app, "_state", state)
    monkeypatch.setattr(app.computer_bar, "before_request", lambda *args: None)
    def old_request(*args):
        state["request_generation"] = 2
        raise app.backend.BackendError("Old timeout")
    monkeypatch.setattr(app.backend, "chat", old_request)
    app._send_chat_message("browser status", generation=1)
    assert state["response"] == "New reply" and state["automation_polling"]
