"""Offline feature parity checks; no real clipboard, sends, OS input or models."""
from types import SimpleNamespace
import pytest

from tests.test_island_runtime import run_async
from services.friday_island_server.tools import DesktopTools


@run_async
async def test_features_cover_every_command_family_and_guides_are_allowlisted():
    from services.automation.command_phrases import PHRASE_GROUPS
    tools = DesktopTools()
    result = await tools.request('owner', 'features')
    assert set(PHRASE_GROUPS) <= {row['key'] for row in result['items']}
    assert {'care', 'presence', 'phone_handoff'} <= {row['key'] for row in result['items']}
    assert all(row['examples'] and row['description'] for row in result['items'])
    with pytest.raises(ValueError): await tools.request('owner', 'guide', value='../../.env')


@run_async
async def test_plugin_inventory_is_live_and_omits_internal_paths_and_errors(monkeypatch):
    from services import plugin_runtime
    manager = SimpleNamespace(list_plugins=lambda: [dict(id='focus', name='Focus', description='Timer', enabled=True,
        status='loaded', commands=[{'help': 'Timer', 'examples': ['focus 25']}], error='private path', folder='private')])
    monkeypatch.setattr(plugin_runtime, 'current_manager', lambda: manager)
    row = (await DesktopTools().request('owner', 'plugins'))['items'][0]
    assert row['id'] == 'focus' and row['commands'][0]['examples'] == ['focus 25']
    assert 'folder' not in row and 'error' not in row


@run_async
async def test_file_actions_reuse_stamped_canonical_context_and_connection_handles(monkeypatch, tmp_path):
    from services.files import assistant
    from services.files.search import FileHit
    from core.config import config
    path = tmp_path / 'fixture.txt'; path.write_text('fixture')
    monkeypatch.setattr(config, 'FILE_SEARCH_ENABLED', True)
    monkeypatch.setattr(assistant, 'find_files', lambda query: [FileHit(str(path), path.name)])
    opened, revealed = [], []
    monkeypatch.setattr(assistant.os, 'startfile', opened.append)
    monkeypatch.setattr(assistant.subprocess, 'Popen', revealed.append)
    tools = DesktopTools()
    row = (await tools.request('owner', 'files_search', value='fixture'))['results'][0]
    assert not (await tools.request('another', 'files_open', row['id']))['ok']
    assert (await tools.request('owner', 'files_open', row['id']))['ok']
    assert (await tools.request('owner', 'files_reveal', row['id']))['ok']
    assert opened == [str(path)]
    assert revealed == [['explorer', '/select,', str(path)]]
    await tools.request('another', 'files_search', value='fixture')
    assert 'expired' in (await tools.request('owner', 'files_open', row['id']))['text']
    row = (await tools.request('owner', 'files_search', value='fixture'))['results'][0]
    path.write_text('changed since result')
    result = await tools.request('owner', 'files_open', row['id'])
    assert not result['ok'] and 'changed since' in result['text']
    assert len(opened) == 1
    await tools.request('owner', 'close')
    assert not (await tools.request('owner', 'files_open', row['id']))['ok']


def test_selected_text_reading_requires_original_window():
    from services.friday_island_server.focus import requires_target
    assert requires_target('read this')
    assert requires_target('read the selected text')


@run_async
async def test_native_launch_gate_checks_canonical_and_private_pending(monkeypatch):
    from services.friday_island_server.runtime import FridayRuntime
    from services.mind import coaching_commands
    from interfaces.api.routes import chat
    async def automation_status(): return {'awaiting_reply': False}
    monkeypatch.setattr(chat, 'automation_status', automation_status)
    runtime = FridayRuntime()
    monkeypatch.setattr(runtime, 'pending', lambda: True)
    assert (await runtime.action('local_ready'))['pending']
    monkeypatch.setattr(runtime, 'pending', lambda: False)
    monkeypatch.setattr(coaching_commands, 'pending', lambda: True)
    assert (await runtime.action('local_ready'))['pending']
    monkeypatch.setattr(coaching_commands, 'pending', lambda: False)
    assert not (await runtime.action('local_ready'))['pending']


def test_private_coaching_and_remote_notices_use_island_and_respect_gaming(monkeypatch):
    from services.friday_island_server import events
    from services.reminders import service
    from services.remote import desktop
    from services import desktop_visibility
    sent = []
    monkeypatch.setattr(events, 'connected', lambda: True)
    monkeypatch.setattr(events, 'publish_private', lambda *args: sent.append(args))
    monkeypatch.setattr(service, '_show_toast', lambda *a, **kw: pytest.fail('private notice became Windows popup'))
    assert service.show_toast('FRIDAY', 'Private care fixture', cognition_text='Redacted private receipt', mirror_telegram=False)
    desktop.notify('Private phone notice')
    assert sent == [('Private care fixture', False), ('Private phone notice',)]
    monkeypatch.setattr(desktop_visibility, 'suppressed', lambda: True)
    desktop.notify('Must wait during gaming')
    assert len(sent) == 2


@run_async
async def test_redacted_command_result_is_private_in_island_response(monkeypatch):
    from interfaces.api.routes import chat
    from services.automation.results import ActionResult
    from services.friday_island_server.runtime import local_turn
    async def action(*args, **kwargs): return ActionResult(True, 'private clipboard fixture', memory_message='redacted clipboard')
    monkeypatch.setattr(chat, 'try_system_action', action)
    with local_turn():
        result = await chat.chat(chat.ChatRequest(message='read my clipboard', speak=False))
    assert result.private and result.response == 'private clipboard fixture'


@run_async
async def test_voice_clipboard_is_private_and_logs_only_redacted_receipt(monkeypatch, caplog):
    from interfaces.api.routes import voice
    from services.automation.results import ActionResult
    from services.friday_island_server.runtime import local_turn
    async def action(*args, **kwargs): return ActionResult(True, 'private clipboard voice fixture', memory_message='redacted clipboard')
    monkeypatch.setattr(voice, 'try_system_action', action)
    with local_turn():
        result = await voice._reply('read my clipboard', voice.VoiceRequest(speak=False))
    assert result.private and result.response == 'private clipboard voice fixture'
    assert 'private clipboard voice fixture' not in caplog.text
