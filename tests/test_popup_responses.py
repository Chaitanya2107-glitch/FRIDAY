"""A response must still reach the command bar after its first timer tick."""

from types import SimpleNamespace

from interfaces.popup import app


def test_poll_timer_survives_pending_request_and_stops_after_reply(monkeypatch):
    state = dict(app._state, response_ready=False, automation_polling=False)
    monkeypatch.setattr(app, "_state", state)
    stopped, shown = [], []
    monkeypatch.setattr(app, "user32", SimpleNamespace(KillTimer=lambda hwnd, timer: stopped.append(timer)))
    monkeypatch.setattr(app, "_show_reply", lambda hwnd, edit: shown.append(state["response"]))
    procedure = app._make_wndproc({"edit": 2})

    # The 100 ms timer fires before the network request has completed.
    procedure(1, app.WM_TIMER, app.POLL_TIMER_ID, 0)
    assert stopped == []
    state.update(response="It's 2 PM.", response_ready=True)
    procedure(1, app.WM_TIMER, app.POLL_TIMER_ID, 0)
    assert shown == ["It's 2 PM."]
    assert stopped == [app.POLL_TIMER_ID] and not state["response_ready"]


def test_poll_timer_keeps_running_between_automation_updates(monkeypatch):
    state = dict(app._state, response_ready=False, automation_polling=True)
    monkeypatch.setattr(app, "_state", state)
    stopped, shown = [], []
    monkeypatch.setattr(app, "user32", SimpleNamespace(KillTimer=lambda hwnd, timer: stopped.append(timer)))
    monkeypatch.setattr(app, "_show_reply", lambda hwnd, edit: shown.append(state["response"]))
    procedure = app._make_wndproc({"edit": 2})
    procedure(1, app.WM_TIMER, app.POLL_TIMER_ID, 0)
    state.update(response="Working", response_ready=True)
    procedure(1, app.WM_TIMER, app.POLL_TIMER_ID, 0)
    assert stopped == [] and shown == ["Working"]
    state.update(response="Done", response_ready=True, automation_polling=False)
    procedure(1, app.WM_TIMER, app.POLL_TIMER_ID, 0)
    assert stopped == [app.POLL_TIMER_ID] and shown == ["Working", "Done"]
