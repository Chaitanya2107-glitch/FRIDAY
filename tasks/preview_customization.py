"""Render every native settings tab using synthetic in-memory data only."""
import copy
import ctypes
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PreviewClient:
    rows = {
        'screen_apps': [{'name': 'chrome', 'value': {'allowed': True}, 'label': 'chrome · Allowed'},
                        {'name': 'powershell', 'value': {'allowed': False}, 'label': 'powershell · Blocked'}],
        'contacts': [{'name': 'alex', 'value': {'number': '+447700900123'}},
                     {'name': 'family', 'value': {'number': '+447700900456'}},
                     {'name': 'team', 'value': {'number': '+447700900789'}}],
        'routines': [{'name': 'focus session', 'value': {'steps': ['open vs code', 'play my focus playlist', 'set volume to 25']}},
                     {'name': 'morning setup', 'value': {'steps': ['open chrome', 'set volume to 35']}}],
        'projects': [{'name': 'friday studio', 'value': {'path': 'C:/Projects/friday-studio',
                      'repo': 'studio/friday', 'sites': ['https://studio.example'],
                      'resume': ['open the terminal', 'open the folder', 'open vs code']}}],
        'modes': [{'name': 'study', 'value': {'steps': ['open vs code', 'set volume to 25'], 'quiet': True}},
                  {'name': 'work', 'value': {'steps': [], 'quiet': True}},
                  {'name': 'chill', 'value': {'steps': ['play music'], 'quiet': False}}],
    }

    def load(self, section):
        return {'items': copy.deepcopy(self.rows[section]), 'revision': 'a' * 64, 'active': None}

    def save(self, *args):
        raise ValueError('Preview only. No settings were saved.')

    def delete(self, *args):
        raise ValueError('Preview only. No settings were deleted.')


def main(output='customization-preview'):
    import tkinter as tk
    from PIL import ImageGrab
    from interfaces.settings.app import SettingsWindow
    ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    window = SettingsWindow(root, PreviewClient())
    root.attributes('-topmost', True)
    folder = (ROOT / 'tasks' / output).resolve()
    assert folder.is_relative_to((ROOT / 'tasks').resolve())
    folder.mkdir(exist_ok=True)
    results = []
    try:
        for index, (section, editor) in enumerate(window.editors.items()):
            window.notebook.select(index)
            deadline = time.monotonic() + 5
            while editor.data is None or editor.busy:
                root.update()
                if time.monotonic() > deadline:
                    raise RuntimeError('Preview did not load')
                time.sleep(.02)
            root.update_idletasks()
            root.update()
            time.sleep(.15)
            box = (root.winfo_rootx(), root.winfo_rooty(),
                   root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())
            ImageGrab.grab(bbox=box).save(folder / (section + '.png'))
            results.append({'section': section, 'width': root.winfo_width(), 'height': root.winfo_height(),
                            'fields': list(editor.form.controls), 'screenshot': section + '.png'})
    finally:
        window.close()
    (folder / 'summary.json').write_text(json.dumps({'synthetic_only': True, 'tabs': results}, indent=2), encoding='utf-8')
    print(json.dumps({'tabs_captured': len(results), 'folder': str(folder)}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='customization-preview')
    main(parser.parse_args().output)
