"""Actions, optional dependency fallbacks, native hotkey loop and host wiring."""
import asyncio
import json
import re
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.smart_clipboard import detectors, maths
from plugins.smart_clipboard.detectors import Dictionary, color, format_json, time_result
from plugins.smart_clipboard.maths import MathActions, safe_arithmetic
from plugins.smart_clipboard.registry import Action
from plugins.smart_clipboard.units import Units
from tests.smart_clipboard_support import FakeAPI, FakeActivity, setup_clipboard


def choose(controller, api, provider, text, label):
    provider.copy(text)
    controller.poll()
    action = next(a for a in api.cards[-1]['actions'] if a['label'] == label)
    result = controller.perform(action['payload'])
    assert result['ok'], result
    return controller.result


def test_math_solve_evaluate_steps_and_copy_result():
    controller, api, provider, _, now = setup_clipboard()
    value = choose(controller, api, provider, '3x+5=20', 'Solve')
    assert '5' in value and 'Working:' in value
    assert api.cards[-2]['body'] == 'x = 5'
    assert api.cards[-1]['actions'][0]['label'] == 'Copy result'
    assert controller.perform(api.cards[-1]['actions'][0]['payload'])['ok']
    assert provider.writes[-1] == value
    before = len(api.cards)
    controller.poll()
    assert len(api.cards) == before
    now[0] += 3
    assert choose(controller, api, provider, '12*(4+3)', 'Evaluate').startswith('84')
    assert all(len(card['body']) <= 80 for card in api.cards)


@pytest.mark.parametrize('text,expected', [
    ('5 km to miles', '3.106855961 mi'), ('3.5 lb in kg', '1.587573295 kg'),
    ('72 F', '22.22222222 C'), ('32 F to C', '0 C'), ('0 C to F', '32 F'),
    ('1 gal to L', '3.785411784 L'), ('36 km/h to m/s', '10 m/s'),
    ('1 MiB in B', '1048576 B'), ('8 bit to B', '1 B'),
])
def test_units_actions_without_pint(text, expected, monkeypatch):
    monkeypatch.setattr('plugins.smart_clipboard.units.installed', lambda name: False)
    controller, api, provider, _, _ = setup_clipboard()
    assert choose(controller, api, provider, text, 'Convert') == expected


@pytest.mark.parametrize('text', ['-500 C to F', '5 km to kg', '1 unknown to kg'])
def test_unit_errors_are_safe(text):
    with pytest.raises(ValueError):
        Units().convert(text)


def test_url_actions_only_open_on_request_and_clean_copy(monkeypatch):
    opened = []
    monkeypatch.setattr(detectors.webbrowser, 'open', lambda text: opened.append(text) or True)
    controller, api, provider, _, _ = setup_clipboard()
    raw = 'https://example.com/path?utm_source=one&UTM_medium=two&fbclid=x&gclid=y&si=z&q=keep#part'
    provider.copy(raw)
    controller.poll()
    assert not opened
    assert controller.perform(api.cards[-1]['actions'][0]['payload'])['ok']
    assert opened == [raw]
    assert controller.perform(api.cards[-1]['actions'][1]['payload'])['ok']
    assert controller.result == 'https://example.com/path?q=keep#part'
    assert provider.writes == [controller.result]
    assert raw not in json.dumps(api.events)


@pytest.mark.parametrize('text,expected', [
    ('#f00', '#FF0000 · rgb(255, 0, 0) · hsl(0, 100%, 50%)'),
    ('rgb(0, 255, 0)', '#00FF00 · rgb(0, 255, 0) · hsl(120, 100%, 50%)'),
    ('hsl(240, 100%, 50%)', '#0000FF · rgb(0, 0, 255) · hsl(240, 100%, 50%)'),
])
def test_color_action(text, expected):
    controller, api, provider, _, _ = setup_clipboard()
    assert choose(controller, api, provider, text, 'Show color') == expected


def test_json_format_copy_and_never_full_text_in_events():
    controller, api, provider, _, _ = setup_clipboard()
    raw = json.dumps({'private': 'x' * 500, 'list': [1, 2]})
    value = choose(controller, api, provider, raw, 'Format')
    assert value == format_json(raw) and '\n' in value
    assert provider.writes == [value]
    for event in api.events:
        serialized = json.dumps(event)
        assert raw not in serialized and value not in serialized
    assert len(api.cards[-1]['body']) <= 80


def test_timestamp_local_and_utc_and_naive_iso():
    controller, api, provider, _, _ = setup_clipboard()
    value = choose(controller, api, provider, '1700000000', 'Show times')
    assert 'Local:' in value and 'UTC: 2023-11-14 22:13:20' in value
    assert time_result('1700000000000') == value
    assert 'UTC:' in time_result('2024-11-05T12:00:00')


def test_existing_local_path_actions(tmp_path, monkeypatch):
    opened = []
    path = tmp_path / 'sample.txt'
    path.write_text('test', encoding='utf-8')
    monkeypatch.setattr(detectors.os, 'startfile', lambda text: opened.append(text))
    controller, api, provider, _, _ = setup_clipboard()
    provider.copy(str(path))
    controller.poll()
    assert [a['label'] for a in api.cards[-1]['actions']] == ['Open', 'Open containing folder']
    for action in api.cards[-1]['actions']:
        assert controller.perform(action['payload'])['ok']
    assert opened == [str(path), str(path.parent)]
    assert not provider.writes


def test_dictionary_missing_never_downloads_search_is_explicit(monkeypatch):
    monkeypatch.setattr(detectors, 'installed', lambda name: False)
    opened = []
    monkeypatch.setattr(detectors.webbrowser, 'open', lambda text: opened.append(text) or True)
    controller, api, provider, _, _ = setup_clipboard()
    assert choose(controller, api, provider, 'serendipity', 'Search online') is None
    assert opened == ['https://www.google.com/search?q=define%20serendipity']
    dictionary = Dictionary()
    assert dictionary.wordnet is None
    dictionary.wordnet = SimpleNamespace(synsets=lambda text: [SimpleNamespace(definition=lambda: 'a local definition')])
    assert dictionary.define('word') == 'a local definition'
    dictionary.wordnet = SimpleNamespace(synsets=lambda text: [])
    assert dictionary.define('word').startswith('No entry')


def test_define_action_with_installed_wordnet_and_missing_corpus_fallback(monkeypatch):
    import sys
    fake_wordnet = SimpleNamespace(ensure_loaded=lambda: None,
                                  synsets=lambda text: [SimpleNamespace(definition=lambda: 'a fortunate coincidence')])
    monkeypatch.setitem(sys.modules, 'nltk.corpus', SimpleNamespace(wordnet=fake_wordnet))
    monkeypatch.setattr(detectors, 'installed', lambda name: name == 'nltk')
    controller, api, provider, _, _ = setup_clipboard()
    assert choose(controller, api, provider, 'serendipity', 'Define') == 'a fortunate coincidence'
    def missing():
        raise LookupError('Offline corpus is not installed')
    fake_wordnet.ensure_loaded = missing
    controller, api, provider, _, _ = setup_clipboard()
    provider.copy('serendipity')
    controller.poll()
    assert api.cards[-1]['actions'][0]['label'] == 'Search online'


def test_chemistry_optional_and_fake_installed_package(monkeypatch):
    import sys
    monkeypatch.setattr(detectors, 'installed', lambda name: name == 'periodictable')
    monkeypatch.setitem(sys.modules, 'periodictable', SimpleNamespace(formula=lambda text: SimpleNamespace(mass=98.079)))
    controller, api, provider, _, _ = setup_clipboard()
    assert choose(controller, api, provider, 'H2SO4', 'Molar mass') == '98.079 g/mol'
    monkeypatch.setattr(detectors, 'installed', lambda name: False)
    controller, *_ = setup_clipboard()
    assert controller.registry.classify('H2SO4')[0] is None


def test_plain_ast_fallback_and_late_service_lookup(monkeypatch):
    monkeypatch.setattr(maths, 'installed', lambda name: False)
    api = FakeAPI()
    actions = MathActions(api)
    assert actions.run('12*(4+3)') == '84'
    assert actions.run('sqrt(2)').startswith('1.41421')
    assert not actions.symbolic()
    assert maths.math_score('3x+5=20', False) == 0
    with pytest.raises(ValueError):
        actions.run('3x+5=20')
    calls = []
    api.services['math_engine'] = SimpleNamespace(calculate=lambda text: calls.append(text) or 'x = 5')
    assert actions.symbolic() and actions.run('3x+5=20') == 'x = 5'
    assert calls == ['solve 3*x+5=20 for x']
    del api.services['math_engine']
    assert actions.run('2^10') == '1024'


@pytest.mark.parametrize('text', [
    "__import__('os')", "__import__('os').system('whoami')", '(1).__class__',
    'math.sqrt(4)', "open('file')", '(lambda:1)()', '[1][0]', 'True + 1',
    '[x for x in (1,2)]', '2**999999999', '9**9**9', 'float("inf")',
    '1e999', '1/0', 'sqrt(-1)', 'sqrt(' * 20 + '1' + ')' * 20,
])
def test_arithmetic_rejects_dangerous_or_unbounded_input(text):
    with pytest.raises((ValueError, SyntaxError, ZeroDivisionError, OverflowError, KeyError)):
        safe_arithmetic(text)


@pytest.mark.parametrize('command,text,expected', [
    ('solve clipboard', '3x+5=20', '5'),
    ('convert clipboard', '5 km to miles', '3.1068'),
    ('clean clipboard link', 'https://example.com?utm_source=secret', 'https://example.com'),
])
def test_commands_execute_in_memory_and_return_generic_reply(command, text, expected):
    controller, api, provider, _, _ = setup_clipboard()
    provider.copy(text)
    value = controller.command(re.fullmatch('.+', command))
    assert value['ok'] and expected in controller.result
    assert text not in value['text']


def test_stale_expired_changed_sensitive_and_faulting_actions(caplog):
    controller, api, provider, _, now = setup_clipboard()
    provider.copy('2+2')
    controller.poll()
    payload = api.cards[-1]['actions'][0]['payload']
    now[0] += 6
    assert controller.perform(payload)['error'] == 'expired'
    provider.copy('secret', app='bitwarden')
    assert controller.perform(payload)['error'] == 'expired'
    assert controller.latest is None
    controller.registry.register('broken', lambda t: 1 if t == 'fault!' else 0,
                                 [Action('crash', 'Crash', lambda t: (_ for _ in ()).throw(RuntimeError(t)))])
    provider.copy('fault!')
    now[0] += 3
    controller.poll()
    assert not controller.perform(api.cards[-1]['actions'][0]['payload'])['ok']
    assert 'fault!' not in caplog.text


@pytest.mark.parametrize('private', [True, False])
def test_clipboard_changes_during_action_discards_result(private):
    controller, api, provider, _, now = setup_clipboard()
    def changing(text):
        now[0] += 3
        provider.copy('private', app='bitwarden') if private else provider.copy('5 km to miles')
        return 'must not be shown'
    controller.registry.register('changing', lambda t: 1 if t == 'change!' else 0,
                                 [Action('change', 'Change', changing)])
    provider.copy('change!')
    controller.poll()
    assert controller.perform(api.cards[-1]['actions'][0]['payload'])['error'] == 'expired'
    assert controller.result is None and len(api.cards) == (1 if private else 2)
    if not private:
        assert api.cards[-1]['actions'][0]['label'] == 'Convert'
    assert all('must not be shown' not in card['body'] for card in api.cards)


def test_cancellation_during_action_discards_result_and_prevents_copy():
    controller, api, provider, _, _ = setup_clipboard()
    def cancelled(text):
        api.stop_event.set()
        return 'must not be copied'
    controller.registry.register('cancelling', lambda t: 1 if t == 'cancel!' else 0,
                                 [Action('format', 'Format', cancelled)])
    provider.copy('cancel!')
    controller.poll()
    assert controller.perform(api.cards[-1]['actions'][0]['payload'])['error'] == 'expired'
    assert controller.result is None and not provider.writes and len(api.cards) == 1


def test_unload_does_not_invert_host_and_controller_locks(monkeypatch):
    from plugins.smart_clipboard import main
    controller, api, provider, _, _ = setup_clipboard()
    monkeypatch.setattr(main, '_controller', controller)
    host_lock = threading.RLock()
    at_lookup, start_lookup = threading.Event(), threading.Event()
    def lookup(name):
        at_lookup.set()
        start_lookup.wait(2)
        with host_lock:
            return None
    api.get_service = lookup
    provider.copy('2+2')
    worker = threading.Thread(target=controller.poll, daemon=True)
    worker.start()
    assert at_lookup.wait(2)
    def host_unload():
        with host_lock:
            api.stop_event.set()
            start_lookup.set()
            main.unload()
    closer = threading.Thread(target=host_unload, daemon=True)
    closer.start()
    closer.join(2)
    worker.join(2)
    assert not closer.is_alive() and not worker.is_alive()
    assert controller.latest is None and not api.cards


def test_hotkey_failure_message_and_cleanup_without_native_registration(caplog):
    controller, api, _, _, _ = setup_clipboard()
    closed = []
    stop = threading.Event()
    class FakeHotkey:
        def register(self, spec):
            assert spec == 'Ctrl+Shift+Alt+V'
            return False
        def pressed(self):
            stop.set()
            return False
        def close(self):
            closed.append(True)
    controller.hotkey_factory = FakeHotkey
    controller.hotkeys(stop)
    assert 'hotkey unavailable' in caplog.text
    assert api.cards[-1]['title'] == 'Clipboard hotkey unavailable'
    assert closed


def test_hotkey_adapter_crash_does_not_discard_clipboard_commands():
    controller, api, provider, _, _ = setup_clipboard()
    provider.copy('5 km to miles')
    controller.poll()
    def unavailable():
        raise OSError('Unavailable native hotkey API')
    controller.hotkey_factory = unavailable
    controller.hotkeys(threading.Event())
    assert controller.latest == '5 km to miles'
    assert controller.command(re.fullmatch('.+', 'convert clipboard'))['ok']
    assert '3.1068' in controller.result


def test_hotkey_bypasses_threshold_with_fake_message_pump():
    controller, api, provider, _, _ = setup_clipboard()
    api.settings['smart_clipboard.confidence_threshold'] = 1
    provider.copy('2+2')
    controller.poll()
    assert not api.cards
    stop = threading.Event()
    class FakeHotkey:
        def register(self, spec):
            return True
        def pressed(self):
            stop.set()
            return True
        def close(self):
            pass
    controller.hotkey_factory = FakeHotkey
    controller.hotkeys(stop)
    assert api.cards[-1]['body'] == '4'


def test_real_host_fake_clipboard_router_reload_and_event_privacy(tmp_path, monkeypatch, caplog):
    from services.event_bus import EventBus
    from services.plugin_api import PluginAPI
    from services.plugin_manager import PluginManager
    from services import plugin_runtime
    from services.automation import clipboard, intent
    controller, _, provider, _, _ = setup_clipboard()
    provider.copy('5 km to miles')
    monkeypatch.setattr(clipboard, 'read_snapshot', provider.read)
    monkeypatch.setattr(clipboard, 'sequence_number', provider.sequence_number)
    monkeypatch.setattr(clipboard, 'set_text', lambda text, **kwargs: provider.write(text))
    monkeypatch.setattr(PluginAPI, 'every', lambda *args: None)
    monkeypatch.setattr(PluginAPI, 'run_background', lambda *args: None)
    code = tmp_path / 'code'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'plugins' / 'smart_clipboard', code / 'smart_clipboard')
    manager = PluginManager(code, tmp_path / 'data', bus=EventBus(), builtin_matcher=plugin_runtime.builtin_matches)
    monkeypatch.setattr(plugin_runtime, '_manager', manager)
    try:
        manager.scan()
        assert manager.list_plugins()[0]['status'] == 'loaded'
        controller = manager.get_service('smart_clipboard')
        controller.activity = FakeActivity()
        controller.poll()
        assert manager.command('convert clipboard')['ok']
        provider.copy('3x+5=20')
        result = asyncio.run(intent._try_system_action('solve clipboard', 'ollama'))
        assert result.success and '5' in controller.result
        result = asyncio.run(intent._try_system_action("what's on my clipboard", 'ollama'))
        assert result.success and 'Solve' in result.message
        assert '3x+5=20' not in result.message
        remote_token = intent.remote_request.set(True)
        try:
            result = asyncio.run(intent._try_system_action('convert clipboard', 'ollama'))
            assert not result.success
        finally:
            intent.remote_request.reset(remote_token)
        secret = 'flagged-content-never-read'
        provider.copy(secret, flags={'CanUploadToCloudClipboard': 0})
        controller.poll()
        assert secret not in json.dumps(manager.bus.recent()) + caplog.text
        assert not list((tmp_path / 'data').rglob('*.json'))
        # An Action imported normally also works with the host's isolated class.
        registry = manager.get_service('clipboard_actions')
        remove = registry.register('external', lambda text: 1 if text == 'external!' else 0,
                                   [Action('external', 'External action', lambda text: 'external result')])
        assert registry.classify('external!')[0].name == 'external'
        remove()
        manager.scan(force=True)
        assert controller.latest is None
        current = manager.get_service('smart_clipboard')
        assert current is not controller and current.latest is None
        manager.set_enabled('smart_clipboard', False)
        assert manager.get_service('clipboard_actions') is None
    finally:
        manager.close()
        manager.bus.close()
