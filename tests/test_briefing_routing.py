"""Real plugin host and local chat/voice routing; providers must never be reached."""
import asyncio
import json
from pathlib import Path
import shutil

import pytest

from briefing_fakes import Clock
from interfaces.api.routes import chat, voice
from services import briefing_runtime, plugin_runtime
from services.automation import intent
from services.event_bus import EventBus
from services.plugin_manager import PluginManager
from services.proactive import timetable, watcher


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    monkeypatch.setattr(intent.media, 'has_player', lambda: True)
    source = Path(__file__).resolve().parents[1] / 'plugins'
    for name in ['briefings', 'schedule_alerts', 'todo']:
        shutil.copytree(source / name, tmp_path / 'code' / name, ignore=shutil.ignore_patterns('__pycache__'))
    manager = PluginManager(tmp_path / 'code', tmp_path / 'user', bus=EventBus(), builtin_matcher=plugin_runtime.builtin_matches)
    monkeypatch.setattr(plugin_runtime, '_manager', manager)
    manager.scan()
    brief = manager.get_service('briefings')
    assert brief and manager.get_service('schedule')
    clock = Clock()
    brief.now = brief.builder.now = clock.now
    brief.desktop, brief.quiet = lambda: {'fullscreen': False}, lambda: False
    brief.builder.battery = lambda: None
    def forbidden(*args, **kwargs):
        pytest.fail('Legacy briefing, provider or secondary speech was reached')
    monkeypatch.setattr(watcher.briefing, 'build', forbidden)
    monkeypatch.setattr(chat, 'build_search_context', forbidden)
    monkeypatch.setattr(voice, 'build_search_context', forbidden)
    monkeypatch.setattr(chat, '_speak_in_background', forbidden)
    monkeypatch.setattr(voice, '_speak_in_background', forbidden)
    yield manager, brief, clock
    manager.close()
    manager.bus.close()


@pytest.mark.parametrize('text', ['brief me', 'morning brief', 'night brief', 'briefing', 'morning briefing',
                                'give me a daily briefing', "what's my briefing", 'read me the morning briefing'])
def test_chat_routes_all_briefing_aliases_locally_without_provider(hosted, text):
    _, _, _ = hosted
    reply = asyncio.run(chat.chat(chat.ChatRequest(message=text, provider='not-a-provider', speak=True)))
    assert reply.action_success and reply.provider == 'local' and reply.model == 'briefings'
    assert reply.private and reply.tokens_used == 0
    assert len(reply.response.splitlines()) <= 6


def test_voice_and_intent_are_offline_and_current_offer_owns_skip(hosted):
    manager, brief, _ = hosted
    reply = asyncio.run(voice._reply('brief me', voice.VoiceRequest(provider='not-a-provider', speak=True)))
    assert reply.private and reply.provider == 'local' and reply.model == 'briefings'
    assert not plugin_runtime.builtin_matches('skip')
    assert asyncio.run(intent.try_system_action('snooze 30', 'not-a-provider')).success
    assert not brief.matches('skip')
    assert plugin_runtime.builtin_matches('skip')  # The normal media command owns skip again.
    assert manager.get_service('schedule') is not None


def test_legacy_explicit_action_is_redirected_without_weather(hosted):
    _, brief, _ = hosted
    assert len(watcher.run_proactive_command({'action': 'briefing'}).splitlines()) <= 6
    assert brief.state['delivered']['morning']


def test_disabled_installed_plugin_does_not_resurrect_legacy_weather(hosted, monkeypatch):
    manager, _, _ = hosted
    manager.set_enabled('briefings', False)
    monkeypatch.setattr(briefing_runtime, 'installed', lambda name='briefings': True)
    reply = asyncio.run(chat.chat(chat.ChatRequest(message='brief me', provider='not-a-provider')))
    assert not reply.action_success and 'unavailable' in reply.response


def test_todo_completion_timestamp_is_stable_and_legacy_rows_are_not_redated(hosted):
    manager, _, _ = hosted
    todos = manager.get_service('todo')
    todos.change('add', 'Read notes')
    first = todos.change('done', 1)['data']['items'][0]
    assert first['done_at']
    assert todos.change('done', 1)['data']['items'][0]['done_at'] == first['done_at']
    assert todos.stats()['completed'] == 1
    todos.change('clear_done')
    assert todos.stats()['completed'] == 1
    data = {'version': 1, 'next_id': 3, 'items': [{'id': 2, 'text': 'Old completed item', 'done': True}]}
    todos.path.write_text(json.dumps(data))
    assert 'done_at' not in todos.change('done', 2)['data']['items'][0]


def test_no_offer_never_claims_skip_even_with_no_media_player(hosted, monkeypatch):
    manager, brief, _ = hosted
    monkeypatch.setattr(intent.media, 'has_player', lambda: False)
    assert not brief.matches('skip')
    assert manager.command('skip') is None


def test_manual_real_store_projection_through_plugin_host(hosted):
    manager, brief, clock = hosted
    timetable.path.write_text(json.dumps([dict(day='monday', subject='Physics', start='10:00', end='11:00', room='B-4')]))
    result = manager.command('brief me')
    assert result['ok'] and 'Physics' in result['text'] and 'B-4' in result['text']
    assert len(result['text'].splitlines()) <= 6
    alerts = manager.get_service('schedule_alerts')
    alerts.now = clock.now
    clock.value = clock.now().replace(hour=9, minute=45)
    alerts.tick()
    assert len(manager.bus.recent('schedule.class_soon')) == 1
    from plugins.schedule_alerts.main import Alerts
    restored = Alerts(alerts.api, alerts.adapter, clock.now)
    restored.tick()
    assert len(manager.bus.recent('schedule.class_soon')) == 1
    clock.value = clock.now().replace(minute=55)
    restored.tick()
    assert len(manager.bus.recent('schedule.class_soon')) == 2
