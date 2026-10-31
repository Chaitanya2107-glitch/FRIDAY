"""Render six actual native college tabs using synthetic fixtures, without a backend."""
import hashlib
import json
from pathlib import Path
import sys
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from college_fakes import FakeClient


class PreviewClient(FakeClient):
    def save(self, *args, **kwargs):
        raise ValueError('Synthetic preview: saving is disabled.')

    def delete(self, *args, **kwargs):
        raise ValueError('Synthetic preview: deletion is disabled.')

    def confirm(self, *args, **kwargs):
        raise ValueError('Synthetic preview: confirmation is disabled.')


def main():
    import tkinter as tk
    from PIL import ImageGrab
    from interfaces.college import launcher
    from interfaces.college.app import CollegeWindow
    from interfaces.college import viewmodel
    class PreviewClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2030, 1, 7, 8)
    viewmodel.datetime = PreviewClock  # Synthetic date shared by every displayed countdown.
    launcher.dpi_awareness()
    root = tk.Tk()
    client = PreviewClient()
    window = CollegeWindow(root, client)
    root.attributes('-topmost', True)
    folder = (ROOT / 'tasks' / 'college-schedules-preview').resolve()
    assert folder.is_relative_to((ROOT / 'tasks').resolve())
    folder.mkdir(exist_ok=True)
    result = []
    try:
        for key, tab in window.tabs.items():
            window.notebook.select(tab)
            tab.load()
            deadline = time.monotonic() + 8
            while tab.data is None or tab.busy:
                root.update()
                if time.monotonic() > deadline:
                    raise RuntimeError('Native preview did not load: ' + key)
                time.sleep(.02)
            if key == 'uploads':
                tab.received(client.upload('synthetic.csv'), None)
                tab.review()
                while tab.busy:
                    root.update()
                    time.sleep(.02)
                tab.confirm_button.configure(state='disabled')
            for _ in range(5):
                root.update()
                time.sleep(.03)
            root.update_idletasks()
            file = folder / (key + '.png')
            bbox = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())
            ImageGrab.grab(bbox=bbox).save(file)
            result.append({'tab': key, 'file': str(file.relative_to(ROOT)), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                           'width': root.winfo_width(), 'height': root.winfo_height()})
        assert not window.callback_errors and not client.calls
        (folder / 'summary.json').write_text(json.dumps({'synthetic_only': True, 'tabs': result,
            'mutations_disabled': True, 'callback_errors': window.callback_errors}, indent=2), encoding='utf-8')
        print(json.dumps({'tabs': len(result), 'folder': str(folder), 'synthetic_only': True}))
    finally:
        window.tabs['uploads'].staged = None
        window.close()


if __name__ == '__main__':
    main()
