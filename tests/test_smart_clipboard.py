"""Classification, privacy and orchestration using only fake clipboard providers."""
import json
import logging
import re
from types import SimpleNamespace

import pytest

from plugins.smart_clipboard.main import preview
from plugins.smart_clipboard.registry import Action
from tests.smart_clipboard_support import setup_clipboard


CASES = [
    ('3x+5=20', 'math'), ('x^2-5*x+6=0', 'math'), ('2*x=10', 'math'),
    ('12*(4+3)', 'math'), ('sqrt(2)', 'math'), ('2^10', 'math'), ('1+2', 'math'),
    ('3 * 7', 'math'), ('10 / 2', 'math'), ('(1+2)*3', 'math'), ('abs(-5)', 'math'),
    ('sin(0)', 'math'), ('2*(3+4)', 'math'), ('2**8', 'math'), ('12 - 5', 'math'), ('100 - 20', 'math'),
    ('5 km to miles', 'units'), ('72 F', 'units'), ('3.5 lb in kg', 'units'),
    ('5km to mi', 'units'), ('25 C to F', 'units'), ('273.15 K to C', 'units'),
    ('2 L to mL', 'units'), ('60 mph to km/h', 'units'), ('1024 B to KiB', 'units'),
    ('1 MiB in B', 'units'), ('2 GB to MB', 'units'), ('10 ft to m', 'units'),
    ('8 oz in g', 'units'), ('1 gal to L', 'units'), ('100 cm', 'units'),
    ('https://example.com', 'url'), ('http://localhost:8080/a', 'url'),
    ('https://example.com/a?utm_source=x&q=ok', 'url'),
    ('https://youtu.be/a?si=tracking', 'url'),
    ('#fff', 'color'), ('#123456', 'color'), ('#abcdef', 'color'),
    ('#FF000080', 'color'), ('rgb(255, 0, 0)', 'color'), ('hsl(120, 100%, 50%)', 'color'),
    ('{"a":1}', 'json'), ('[1,2,3]', 'json'), ('{}', 'json'), ('[]', 'json'),
    ('{"a":{"b":[true,null]}}', 'json'),
    ('1700000000', 'timestamp'), ('1700000000000', 'timestamp'),
    ('2024-11-05', 'timestamp'), ('2024-11-05T12:30:00Z', 'timestamp'),
    ('2024-11-05T12:30:00+05:30', 'timestamp'), ('2024-02-29', 'timestamp'),
    ('hello', 'word'), ('hello world', 'word'), ('well-being', 'word'), ("can't", 'word'),
    ('word ' * 100, 'long_text'),
    ('2024/11/05', None), ('11-05-2024', None), ('2024-02-30', None),
    ('2024-13-01', None), ('1.2.3', None), ('v1.2.3', None), ('1.2.3-beta', None),
    ('+1 (555) 123-4567', None), ('555-123-4567', None), ('123-4567', None),
    ('020 7946 0958', None), ('+91 98765 43210', None),
    ('I have 3 apples', None), ('The meeting is at 5', None), ('Order 123 arrived', None),
    ('call me at 12345', None), ('room 42', None),
    ('42', None), ('-42', None), ('3.14', None), ('100000', None), ('+12', None),
    ('$123.45', None), ('£5', None), ('€1,234.56', None), ('₹500', None), ('¥100', None),
    ('USD 5', None), ('$5 + $2', None),
    ("__import__('os')", None), ('(1).__class__', None), ('os.system(1)', None),
    ('2^9999999', None), ('9**9**9', None), ('[x for x in [1]]', None),
    ('5 km to kg', None), ('rgb(999, 0, 0)', None), ('hsl(1,2,3)', None),
    ('{broken:json}', None), ('{"a":NaN}', None), ('ftp://example.com', None),
    ('javascript:alert(1)', None), ('https://user:secret@example.com', None),
    ('not a complete sentence 7', None), ('', None), ('   ', None),
]


@pytest.mark.parametrize('text,expected', CASES)
def test_classifier_table(text, expected):
    controller, *_ = setup_clipboard()
    detector, confidence = controller.registry.classify(text)
    assert (detector.name if detector else None) == expected
    if expected:
        assert confidence >= .8


@pytest.mark.parametrize('flags', [
    {'ExcludeClipboardContentFromMonitorProcessing': 0},
    {'ExcludeClipboardContentFromMonitorProcessing': 1},
    {'CanIncludeInClipboardHistory': 0}, {'CanUploadToCloudClipboard': 0},
    {'CanIncludeInClipboardHistory': None},
])
def test_sensitive_flags_skip_without_reading_content(flags, caplog):
    controller, api, provider, _, _ = setup_clipboard()
    provider.copy('private-password-123', flags=flags)
    controller.poll()
    assert provider.text_reads == 0
    assert controller.latest is None and not api.cards
    assert 'private-password-123' not in caplog.text


@pytest.mark.parametrize('app', ['bitwarden', 'KeepassXC.exe', '1password', 'dashlane', 'nordpass'])
def test_password_manager_blocklist(app):
    controller, api, provider, _, _ = setup_clipboard()
    provider.copy('3x+5=20', app=app)
    controller.poll()
    assert provider.text_reads == 0 and not api.cards


def test_custom_blocklist_and_positive_flags():
    controller, api, provider, _, _ = setup_clipboard()
    api.settings['smart_clipboard.blocklist'] = ['secureapp']
    provider.copy('2+2', app='secureapp')
    controller.poll()
    assert not api.cards
    provider.copy('2+2', flags={'CanUploadToCloudClipboard': 1, 'CanIncludeInClipboardHistory': 1})
    controller.poll()
    assert api.cards[-1]['body'] == '4'


def test_sequence_polling_rate_limit_threshold_and_mood():
    controller, api, provider, _, now = setup_clipboard()
    controller.start()
    assert api.timers[0][0] == .4
    provider.copy('5 km to miles')
    controller.poll()
    assert api.cards[-1]['actions'][0]['label'] == 'Convert'
    assert api.cards[-1]['ttl_s'] == 6
    assert api.events[-1]['topic'] == 'clipboard.action_available'
    assert api.events[-1]['payload']['action_id'] == 'run'
    controller.poll()
    assert provider.reads == 1
    now[0] += 2.99
    provider.copy('2+2')
    controller.poll()
    assert len(api.cards) == 1 and controller.latest == '2+2'
    now[0] += .01
    provider.copy('3+3')
    controller.poll()
    assert len(api.cards) == 2
    api.settings['smart_clipboard.confidence_threshold'] = 1
    now[0] += 3
    provider.copy('4+4')
    controller.poll()
    assert len(api.cards) == 2
    controller.command(re.fullmatch('.+', "what's on my clipboard"))
    assert api.cards[-1]['body'] == '8'


@pytest.mark.parametrize('reason', ['idle', 'fullscreen', 'game', 'sleep', 'idle_event', 'scene_event', 'service'])
def test_suppressed_while_idle_or_busy(reason):
    controller, api, provider, activity, _ = setup_clipboard()
    if reason == 'idle':
        activity.is_idle = True
    elif reason == 'fullscreen':
        activity.is_fullscreen = True
    elif reason in {'game', 'sleep'}:
        activity.current_scene = reason
    elif reason == 'idle_event':
        controller.activity_event({'topic': 'activity.idle_started'})
    elif reason == 'scene_event':
        controller.scene_event({'topic': 'scene.started', 'payload': {'name': 'game'}})
    else:
        api.services['activity'] = SimpleNamespace(is_fullscreen=lambda: True)
    provider.copy('2+2')
    controller.poll()
    assert not api.cards
    controller.command(re.fullmatch('.+', "what's on my clipboard"))
    assert not api.cards


def test_activity_and_scene_end_resume_without_replaying_old_item():
    controller, api, provider, _, _ = setup_clipboard()
    controller.activity_event({'topic': 'activity.idle_started'})
    controller.scene_event({'topic': 'scene.started', 'payload': {'name': 'sleep'}})
    provider.copy('2+2')
    controller.poll()
    controller.activity_event({'topic': 'activity.idle_ended'})
    controller.scene_event({'topic': 'scene.ended', 'payload': {'name': 'sleep'}})
    controller.poll()
    assert not api.cards
    provider.copy('3+3')
    controller.poll()
    assert len(api.cards) == 1


def test_explicit_requests_obey_new_card_rate_limit_but_results_can_refresh():
    controller, api, provider, _, now = setup_clipboard()
    provider.copy('2+2')
    controller.poll()
    assert controller.perform(api.cards[-1]['actions'][0]['payload'])['ok']
    assert len(api.cards) == 2  # Refresh the same card with its result.
    provider.copy('3+3')
    controller.command(re.fullmatch('.+', "what's on my clipboard"))
    assert len(api.cards) == 2
    now[0] += 3
    controller.command(re.fullmatch('.+', "what's on my clipboard"))
    assert api.cards[-1]['body'] == '6'


def test_a_scene_stays_suppressed_until_all_its_active_ids_end():
    controller, api, provider, _, _ = setup_clipboard()
    for scene_id in ('game-one', 'game-two'):
        controller.scene_event({'topic': 'scene.started', 'payload': {'scene_id': scene_id, 'name': 'game'}})
    controller.scene_event({'topic': 'scene.ended', 'payload': {'scene_id': 'game-one', 'name': 'game'}})
    provider.copy('2+2')
    controller.poll()
    assert not api.cards
    controller.scene_event({'topic': 'scene.ended', 'payload': {'scene_id': 'game-two', 'name': 'game'}})
    provider.copy('3+3')
    controller.poll()
    assert api.cards[-1]['body'] == '6'


def test_ignore_own_changes_clear_sensitive_nontext_and_off():
    controller, api, provider, _, _ = setup_clipboard()
    provider.copy('2+2', own=True)
    controller.poll()
    assert not api.cards and controller.latest is None
    provider.copy('5 km to miles')
    controller.poll()
    old_token = controller.token
    provider.copy('result', own=True)
    controller.poll()
    assert controller.token is None and len(api.cards) == 1
    provider.copy('secret', app='bitwarden')
    controller.poll()
    assert controller.latest is None and controller.token is None
    provider.copy(None)
    controller.poll()
    assert controller.latest is None
    assert controller.command(re.fullmatch('.+', 'clipboard off'))['ok']
    provider.copy('2+2')
    controller.poll()
    assert controller.latest is None
    assert controller.command(re.fullmatch('.+', 'clipboard on'))['ok']
    assert api.settings['smart_clipboard.enabled'] is True


def test_extension_registration_actions_and_unregister():
    controller, api, provider, _, _ = setup_clipboard()
    controller.start()
    registry = api.get_service('clipboard_actions')
    unregister = registry.register('custom', lambda t: 1.0 if t == 'custom!' else 0,
                                   [Action('custom', 'Custom action', lambda t: 'custom result')])
    provider.copy('custom!')
    controller.poll()
    assert api.cards[-1]['actions'][0]['label'] == 'Custom action'
    assert controller.perform(api.cards[-1]['actions'][0]['payload'])['ok']
    assert controller.result == 'custom result'
    unregister()
    assert registry.classify('custom!')[0] is None


def test_contents_never_escape_via_logs_events_or_command_replies(caplog):
    controller, api, provider, _, _ = setup_clipboard()
    caplog.set_level(logging.DEBUG)
    raw = 'private long sentence ' * 40
    provider.copy(raw)
    controller.poll()
    reply = controller.command(re.fullmatch('.+', "what's on my clipboard"))
    assert raw not in json.dumps(api.events) + json.dumps(reply) + caplog.text
    assert all(len(card['body']) <= 80 for card in api.cards)
    assert 'private long sentence' not in json.dumps(api.events)
    # Extension/parser exceptions, including SyntaxError's source, stay private.
    def broken(text):
        raise SyntaxError(text)
    controller.registry.register('broken', broken, [])
    controller.registry.classify(raw)
    provider.read = broken
    controller.sequence = None
    controller.poll()
    assert raw not in caplog.text and controller.latest is None


def test_preview_is_one_line_and_bounded():
    assert len(preview('x' * 81)) == 80
    assert preview('one\n two\tthree\x00') == 'one two three'
