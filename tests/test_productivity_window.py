"""Native Tk event-loop checks with an isolated real store and background I/O."""
import gc
import threading
import time
import tkinter as tk

import pytest

from interfaces.productivity.app import ProductivityWindow
from interfaces.productivity.dialogs import Editor, Importer
from services.productivity.store import tracker


def spin(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.root.update()
        if predicate():
            return
        time.sleep(.01)
    pytest.fail('Tracker background operation did not finish')


@pytest.fixture(scope='module')
def root():
    root = tk.Tk()
    root.withdraw()
    yield root
    gc.collect()
    root.destroy()


@pytest.fixture
def app(root, monkeypatch):
    top = tk.Toplevel(root)
    top.withdraw()
    monkeypatch.setattr('interfaces.productivity.dialogs.messagebox.askyesno', lambda *a, **kw: True)
    errors = []
    top.report_callback_exception = lambda *args: errors.append(args)
    tracker.save_habit('Read', list(range(7)))
    tracker.save_task('Buy book', priority='high')
    window = ProductivityWindow(top)
    spin(window, lambda: not window.pending)
    yield window
    spin(window, lambda: not window.pending)
    for draft in list(window.dialogs):
        draft.close(force=True)
    assert not errors and not window.callback_errors
    window.close()
    gc.collect()


def test_three_views_render_and_checkins_update_real_store(app):
    assert len(app.today_tree.get_children()) == 2
    app.show('habits')
    habit = app.data['habits'][0]
    app.habit_tree.selection_set(str(habit['id']))
    app.habit_details()
    assert len(app.history.winfo_children()) == 14
    app.check_habit()
    spin(app, lambda: not app.pending)
    assert app.data['date'] in tracker.snapshot()['habits'][0]['checks']
    app.check_habit()
    spin(app, lambda: not app.pending)
    assert not tracker.snapshot()['habits'][0]['checks']
    app.show('tasks')
    app.filter.set('High priority')
    assert len(app.task_tree.get_children()) == 1
    app.query.set('no match')
    assert not app.task_tree.get_children()


def test_habit_editor_retains_invalid_draft_then_saves(app):
    editor = Editor(app, 'habit')
    editor.name.set('')
    editor.save()
    spin(app, lambda: not editor.busy)
    assert editor in app.dialogs and editor.error.get()
    editor.name.set('Meditate')
    editor.save()
    spin(app, lambda: editor not in app.dialogs and not app.pending)
    assert any(h['name'] == 'Meditate' for h in tracker.snapshot()['habits'])


def test_task_completion_and_pause_are_visible_to_friday(app, monkeypatch):
    from services.mind.workspace import workspace
    app.show('tasks')
    task = app.data['tasks'][0]
    app.task_tree.selection_set(str(task['id']))
    app.pause_task()
    spin(app, lambda: not app.pending)
    assert workspace.tasks()[0]['status'] == 'paused'
    app.pause_task()
    spin(app, lambda: not app.pending)
    monkeypatch.setattr('interfaces.productivity.app.simpledialog.askstring', lambda *a, **kw: '')
    app.finish_task()
    spin(app, lambda: not app.pending)
    assert workspace.tasks(include_finished=True)[0]['status'] == 'completed'
    assert not app.task_tree.get_children()
    app.filter.set('Completed')
    assert len(app.task_tree.get_children()) == 1


def test_slow_io_keeps_tk_responsive_and_close_waits(app):
    thread_ids = []
    completed = []
    main_thread = threading.get_ident()
    def operation():
        thread_ids.append(threading.get_ident())
        time.sleep(.15)
        return 7
    app.submit(operation, lambda value, error: completed.append(value))
    ticks = []
    app.root.after(10, lambda: ticks.append(True))
    app.close()
    assert not app.closed
    spin(app, lambda: bool(completed))
    assert ticks and thread_ids[0] != main_thread and completed == [7]


def test_import_dialog_imports_multiline_and_preserves_bad_csv(app):
    importer = Importer(app)
    importer.csv = True
    importer.input.insert('1.0', 'bad_column\nMissing name')
    importer.save()
    spin(app, lambda: not importer.busy)
    assert importer in app.dialogs and 'name column' in importer.message.get()
    importer.csv = False
    importer.input.delete('1.0', 'end')
    importer.input.insert('1.0', 'Read\nExercise\nDrink water')
    importer.save()
    spin(app, lambda: not app.pending)
    assert len(tracker.snapshot()['habits']) == 3


def test_bottom_controls_remain_visible_at_small_window_size(app):
    app.root.geometry('1050x740')
    app.root.deiconify()
    app.root.update()
    for view in ['today', 'habits', 'tasks']:
        app.show(view)
        app.root.update()
        children = app.views[view].winfo_children()
        controls = children[-1]
        assert controls.winfo_ismapped()
        assert controls.winfo_y() + controls.winfo_height() <= app.views[view].winfo_height()
    app.root.withdraw()
