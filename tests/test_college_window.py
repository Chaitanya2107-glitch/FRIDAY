"""Real withdrawn Tk smoke tests following the existing Customize FRIDAY tests."""
import gc
import threading
import time
import tkinter as tk

import pytest

from college_fakes import FakeClient
from interfaces.college import app as ui, launcher
from interfaces.college.client import Error


def spin(window, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.root.update()
        if predicate():
            return
        time.sleep(.01)
    pytest.fail('Native college request did not finish')


@pytest.fixture(scope='module')
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    gc.collect()
    root.destroy()


@pytest.fixture
def window(monkeypatch, tk_root):
    monkeypatch.setattr(ui.messagebox, 'askyesno', lambda *a, **kw: True)
    root = tk.Toplevel(tk_root)
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = ui.CollegeWindow(root, FakeClient())
    spin(app, lambda: app.tabs['home'].data is not None)
    yield app
    spin(app, lambda: all(not tab.busy for tab in app.tabs.values()) and not app.pending_writes)
    for dialog in list(app.dialogs):
        dialog.close(force=True)
    app.tabs['uploads'].staged = None
    assert not errors and not app.callback_errors
    app.close()
    gc.collect()


def select(window, key):
    tab = window.tabs[key]
    window.notebook.select(tab)
    spin(window, lambda: tab.data is not None and not tab.busy)
    return tab


def test_all_six_tabs_build_and_run_event_loop_with_offthread_api(window):
    assert len(window.notebook.tabs()) == 6
    for key in window.tabs:
        tab = select(window, key)
        assert tab.winfo_exists()
    assert window.tabs['home'].timeline.get_children()
    assert window.tabs['timetable'].grid.get_children()
    assert window.tabs['timetable'].subject_tree.get_children()
    assert window.client.threads
    assert all(thread != threading.get_ident() for thread in window.client.threads)


def test_assignment_filters_and_mark_done_use_http_payload(window):
    tab = select(window, 'deadlines')
    tab.subject.set('DBMS')
    assert tab.tree.get_children() == ('d1',)
    tab.status.set('Done')
    assert tab.tree.get_children() == ()
    tab.status.set('Open')
    tab.tree.selection_set('d1')
    tab.complete()
    spin(window, lambda: not tab.busy)
    call = window.client.calls[-1]
    assert call[:3] == ('save', 'deadlines', 'd1') and call[3]['done'] is True


def test_conflict_retains_draft_and_reloads_without_silent_rebase(window):
    tab = select(window, 'deadlines')
    tab.tree.selection_set('d1')
    tab.edit()
    dialog = window.dialogs[-1]
    dialog.controls['what'].set('My unsaved title')
    window.client.failure = Error('Changed elsewhere. Draft kept.', 409)
    dialog.save()
    spin(window, lambda: not dialog.busy)
    assert dialog.values()['what'] == 'My unsaved title'
    assert str(dialog.save_button['state']) == 'disabled'
    assert 'Changed elsewhere' in dialog.message.get()
    window.client.failure = None
    window.client.data['deadlines'][0]['venue'] = 'New hidden venue'
    window.client.revision = 'b' * 64
    dialog.review()
    spin(window, lambda: str(dialog.save_button['state']) == 'normal')
    dialog.save()
    spin(window, lambda: dialog.closed)
    assert window.client.calls[-1][3]['venue'] == 'New hidden venue'


def test_weekly_reorder_conflict_cannot_rebase_to_a_different_class(window):
    tab = select(window, 'timetable')
    row = tab.data['items'][0]
    from interfaces.college.tabs import open_editor
    dialog = open_editor(window, 'timetable', row, tab.data['revision'])
    dialog.controls['subject'].set('Unsaved DBMS edit')
    window.client.failure = Error('Changed elsewhere', 409)
    dialog.save()
    spin(window, lambda: not dialog.busy)
    window.client.failure = None
    window.client.data['timetable'][0]['subject'] = 'Different class after reorder'
    dialog.review()
    spin(window, lambda: 'template changed' in dialog.message.get())
    assert str(dialog.save_button['state']) == 'disabled'
    assert not window.client.calls


def test_slow_save_disables_fields_keeps_tk_responsive_and_guards_close(window):
    tab = select(window, 'events')
    tab.tree.selection_set('v1')
    tab.edit()
    dialog = window.dialogs[-1]
    window.client.save_delay = .25
    dialog.controls['title'].set('Updated synthetic event')
    dialog.save()
    assert all(str(widget['state']) == 'disabled' for widget, kind in dialog.widgets)
    flag = []
    window.root.after(20, lambda: flag.append(True))
    spin(window, lambda: bool(flag))
    assert dialog.busy
    window.close()
    assert not window.closed
    spin(window, lambda: dialog.closed)


def test_upload_preview_edits_need_review_and_confirm_is_explicit(window):
    tab = select(window, 'uploads')
    staged = window.client.upload('synthetic.csv')  # in-memory test fixture only
    tab.received(staged, None)
    assert tab.dirty() and not window.client.calls
    tab.review()
    spin(window, lambda: tab.reviewed is not None)
    assert str(tab.confirm_button['state']) == 'normal'
    tab.mode.set('replace')
    assert tab.reviewed is None and str(tab.confirm_button['state']) == 'disabled'
    tab.review()
    spin(window, lambda: tab.reviewed is not None)
    window.client.save_delay = .2
    tab.confirm()
    window.close()
    assert not window.closed
    spin(window, lambda: tab.staged is None and not tab.busy)
    assert window.client.calls[-1][0] == 'confirm'


def test_focus_refresh_preserves_upload_preview_and_dialog_drafts(window):
    tab = select(window, 'uploads')
    tab.received(window.client.upload('synthetic.csv'), None)
    rows = list(tab.rows)
    window.refresh(automatic=True)
    assert tab.rows == rows and tab.dirty()
    deadline = select(window, 'deadlines')
    deadline.new()
    dialog = window.dialogs[-1]
    dialog.controls['what'].set('Keep this draft')
    window.refresh(automatic=True)
    assert dialog.controls['what'].get() == 'Keep this draft'


def test_offline_start_and_retry_recover_without_tk_callback_errors(monkeypatch, tk_root):
    client = FakeClient()
    client.failure = Error('FRIDAY backend is not running. Start FRIDAY, then Retry.')
    root = tk.Toplevel(tk_root)
    root.withdraw()
    window = ui.CollegeWindow(root, client)
    spin(window, lambda: not window.tabs['home'].busy)
    assert 'FRIDAY backend is not running' in window.tabs['home'].title['text']
    client.failure = None
    window.refresh()
    spin(window, lambda: window.tabs['home'].data is not None)
    assert 'Connected' in window.connection.get()
    assert not window.callback_errors
    window.close()
    gc.collect()


def test_single_instance_mutex_duplicate_focus_and_release(monkeypatch):
    focused = []
    monkeypatch.setattr(launcher, 'focus_existing', lambda: focused.append(True))
    first = launcher.acquire_instance()
    assert first
    try:
        assert launcher.acquire_instance() is None
        assert focused == [True]
    finally:
        launcher.release_instance(first)
    second = launcher.acquire_instance()
    assert second
    launcher.release_instance(second)


def test_duplicate_launcher_still_requests_backend_start(monkeypatch):
    called = []
    monkeypatch.setattr(launcher, 'acquire_instance', lambda: None)
    monkeypatch.setattr(launcher, 'ensure_backend', lambda: called.append(True))
    ui.main(ensure_backend=True)
    assert called == [True]
