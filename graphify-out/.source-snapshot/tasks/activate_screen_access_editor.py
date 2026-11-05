"""Load tested app-permission controls without changing watching consent or rules."""
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def report(name):
    suites = list(ET.parse(ROOT / 'tasks' / name).getroot().iter('testsuite'))
    counts = {key: sum(int(row.get(key, 0)) for row in suites) for key in ('tests', 'errors', 'failures', 'skipped')}
    assert not counts['errors'] and not counts['failures']
    return counts


def main():
    import psutil
    import win32con
    import win32gui
    import win32process
    from interfaces.settings.launcher import TITLE, launch
    from services.screen_watch.store import ScreenStore
    from tasks.screen_native_probe import api_client, command, reload_desktop, wait
    focused = report('screen-access-final-focused.xml')
    native = report('screen-access-final-ui.xml')
    policy = report('screen-access-final-policy.xml')
    assert focused['tests'] >= 160 and native['tests'] >= 12 and policy['tests'] >= 50
    files = ('services/screen_watch/app_rules.py', 'services/screen_watch/capture.py',
             'services/screen_watch/store.py', 'services/screen_watch/service.py', 'services/customization.py',
             'interfaces/api/routes/customization.py', 'interfaces/settings/app.py', 'interfaces/settings/forms.py',
             'tests/test_screen_app_rules.py', 'tests/test_settings_window.py', 'docs/screen-awareness.md')
    before = ScreenStore().settings()
    receipt = {'decision': 'Load owner-requested app allow/block controls in customization.',
               'envelope': 'Keep watching consent and all app rules unchanged; retain protected-content gates.',
               'sources': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
               'focused': focused, 'native': native, 'policy': policy, 'previous_settings': before}
    target = ROOT / 'tasks/screen-access-editor-activation.json'
    target.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    editor = win32gui.FindWindow(None, TITLE)
    if editor:
        process = psutil.Process(win32process.GetWindowThreadProcessId(editor)[1])
        assert Path(process.cwd()).resolve() == ROOT and 'interfaces.settings' in process.cmdline()
        win32gui.PostMessage(editor, win32con.WM_CLOSE, 0, 0)
        wait(lambda: not win32gui.IsWindow(editor), 12,
             'The existing customization window is still open; save its draft and close it before reloading.')
        process.wait(timeout=8)
    receipt['desktop'] = reload_desktop()
    with api_client() as client:
        if not before['enabled']:
            command(client, 'stop screen awareness')
        elif not before['paused']:
            command(client, 'resume screen awareness')
        response = client.get('/api/v1/customization/screen_apps')
        response.raise_for_status()
        assert isinstance(response.json()['items'], list)
        receipt['saved_rule_count'] = len(response.json()['items'])
        status = client.get('/api/v1/system/status')
        status.raise_for_status()
        receipt['status'] = status.json()['screen_watch']
    assert bool(receipt['status']['enabled']) == bool(before['enabled'])
    if before['enabled']:
        assert bool(receipt['status']['paused']) == bool(before['paused'])
    launch()
    wait(lambda: win32gui.FindWindow(None, TITLE), 20, 'The customization editor did not open.')
    receipt['applied'] = True
    target.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({key: receipt[key] for key in ('applied', 'status', 'saved_rule_count', 'focused', 'native')}, indent=2))


if __name__ == '__main__':
    main()
