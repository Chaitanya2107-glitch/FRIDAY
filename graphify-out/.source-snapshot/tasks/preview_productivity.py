"""Capture only the synthetic tracker window; never seed FRIDAY's personal store."""
from datetime import date, timedelta
import ctypes
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tkinter as tk
from PIL import ImageGrab
from services.mind.cognition import Cognition
from services.mind.workspace import Workspace
from services.productivity.store import Tracker
from interfaces.productivity.app import ProductivityWindow


def main():
    try:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    output = ROOT / 'tasks' / 'productivity-preview'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tracker-preview-', dir=output) as temp:
        work = Workspace(Cognition(Path(temp) / 'demo.db'))
        store = Tracker(work)
        today = date.today()
        names = ['Read 20 pages', 'Move for 30 minutes', 'Drink enough water', 'Practice something new']
        for name in names:
            ident = store.save_habit(name, list(range(7)), 'A small promise to yourself. Show up, one day at a time.')
            with store.db() as conn:
                conn.execute('UPDATE tracker_habits SET created=? WHERE id=?', ((today - timedelta(days=20)).isoformat(), ident))
                for offset in range(1, 6):
                    conn.execute('INSERT INTO tracker_checks(habit_id,day) VALUES(?,?)', (ident, (today - timedelta(days=offset)).isoformat()))
            if name in names[:2]:
                store.check(ident, today.isoformat(), True)
        store.save_task('Finish the database assignment', today.isoformat(), 'high', 'Review the final queries before submitting.')
        store.save_task('Plan next week', (today + timedelta(days=2)).isoformat(), 'normal')
        store.save_task('Pick up a new book', '', 'low')
        root = tk.Tk()
        app = ProductivityWindow(root, store)
        root.geometry(f'{min(1260, root.winfo_screenwidth()-80)}x{min(860, root.winfo_screenheight()-100)}+30+30')
        errors = []
        root.report_callback_exception = lambda *args: errors.append(str(args))
        def pump(seconds=.4):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
        pump(1)
        for view in ['today', 'habits', 'tasks']:
            app.show(view)
            if view == 'habits':
                app.habit_tree.selection_set(app.habit_tree.get_children()[0])
                app.habit_details()
            if view == 'tasks':
                app.task_tree.selection_set(app.task_tree.get_children()[0])
                app.task_details()
            root.lift()
            pump()
            bbox = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())
            ImageGrab.grab(bbox=bbox).save(output / f'{view}.png')
        pump()
        app.close()
        (output / 'result.json').write_text(json.dumps({'views': 3, 'tk_errors': errors, 'callback_errors': [str(e) for e in app.callback_errors], 'personal_data_modified': False}, indent=2))
        print('Synthetic previews saved in tasks/productivity-preview; no personal data modified.')


if __name__ == '__main__':
    main()
