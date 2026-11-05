import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import config
from interfaces.api.app import create_app
from providers.base_provider import ProviderResponse
from services.mind import development as module
from services.mind.cognition import cognition


def write(service, name, content='original'):
    target = service.root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
    return target


@pytest.fixture
def aware(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    root.mkdir()
    service = module.DevelopmentAwareness(root, tmp_path / 'state' / 'development.json')
    monkeypatch.setattr(module, 'development', service)
    return service


def test_initial_baseline_and_unchanged_or_touched_content_are_not_upgrades(aware):
    source = write(aware, 'services/mind/brain.py')
    first = aware.scan()
    assert first['available'] and first['watched_files'] == 1
    assert not first['recent_changes'] and not first['restart_recommended']
    source.touch()
    assert not aware.scan()['recent_changes']
    assert not cognition.latest('observation')


def test_repeated_edits_additions_deletions_and_reversion(aware):
    source = write(aware, 'services/mind/brain.py')
    removed = write(aware, 'providers/old.py')
    aware.scan()
    source.write_text('first edit', encoding='utf-8')
    added = write(aware, 'interfaces/new.py')
    removed.unlink()
    view = aware.scan()
    assert view['recent_changes'][-1]['counts'] == {'added': 1, 'modified': 1, 'deleted': 1}
    assert view['restart_recommended'] and view['recent_edits']
    source.write_text('second edit', encoding='utf-8')
    assert aware.scan()['recent_changes'][-1]['files']['modified'] == ['services/mind/brain.py']
    source.write_text('original', encoding='utf-8')
    write(aware, 'providers/old.py')
    added.unlink()
    reverted = aware.scan()
    assert not reverted['restart_recommended']
    assert not any(reverted['since_startup']['counts'].values())
    assert reverted['recent_edits']  # observed work remains history after a revert


def test_same_size_edit_with_preserved_mtime_is_still_detected(aware):
    source = write(aware, 'main.py', 'first')
    aware.scan()
    stamp = source.stat()
    source.write_text('other', encoding='utf-8')
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert aware.scan()['recent_changes'][-1]['counts']['modified'] == 1


@pytest.mark.parametrize('name,restart,island', [
    ('docs/change.md', False, False), ('tests/test_change.py', False, False),
    ('island/src/main.ts', False, True), ('island/src-tauri/src/main.rs', False, True),
    ('requirements.txt', True, False), ('train_friday.py', True, False),
])
def test_changed_component_drives_reload_guidance(aware, name, restart, island):
    source = write(aware, name)
    aware.scan()
    source.write_text('changed', encoding='utf-8')
    view = aware.scan()
    assert view['restart_recommended'] is restart
    assert view['island_rebuild_recommended'] is island
    assert 'unverified' in view['runtime_verification']


def test_restart_remembers_history_and_detects_work_between_sessions(aware):
    source = write(aware, 'main.py')
    aware.scan()
    source.write_text('live edit', encoding='utf-8')
    aware.scan()
    source.write_text('edited while stopped', encoding='utf-8')
    restarted = module.DevelopmentAwareness(aware.root, aware.path)
    view = restarted.scan()
    assert [e['origin'] for e in view['recent_changes']] == ['during run', 'between runs']
    assert view['history_state'] == 'restored'
    assert not view['restart_recommended']  # new startup baseline; loaded behavior remains unverified
    assert not any(view['since_startup']['counts'].values())
    again = module.DevelopmentAwareness(aware.root, aware.path).scan()
    assert len(again['recent_changes']) == 2


@pytest.mark.parametrize('private', [
    '.env', '.env.example', 'memory/private.py', 'logs/private.py', 'venv/private.py',
    'services/.private.py', 'services/memory/secrets/private.py',
    'services/node_modules/private.py', 'services/__pycache__/private.py',
    'island/node_modules/private.ts', 'island/dist/private.js',
    'island/src-tauri/target/private.rs', 'tasks/private.py',
])
def test_private_runtime_dependencies_and_outputs_are_never_opened(aware, private, monkeypatch):
    target = write(aware, private, 'PRIVATE_SECRET')
    write(aware, 'main.py')
    original = Path.open
    def guarded(path, *args, **kwargs):
        assert path != target, 'An excluded file was opened'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    view = aware.scan()
    assert view['available'] and view['watched_files'] == 1
    assert 'PRIVATE_SECRET' not in aware.path.read_text(encoding='utf-8')


def test_linked_source_roots_and_nested_directories_are_not_followed(aware, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.py').write_text('PRIVATE_OUTSIDE', encoding='utf-8')
    write(aware, 'main.py')
    (aware.root / 'services').mkdir()
    for link in (aware.root / 'providers', aware.root / 'services' / 'linked'):
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
        else:
            link.symlink_to(outside, target_is_directory=True)
    view = aware.scan()
    assert view['available'] and view['watched_files'] == 1


def test_source_root_becoming_a_link_is_unknown(aware, monkeypatch):
    write(aware, 'main.py')
    aware.scan()
    original = module._linked
    monkeypatch.setattr(module, '_linked', lambda path: path == aware.root or original(path))
    assert not aware.scan()['available']
    assert aware.status()['watched_files'] == 1


@pytest.mark.parametrize('limit', ['MAX_FILES', 'MAX_FILE_BYTES', 'MAX_ENTRIES', 'MAX_DEPTH'])
def test_scan_limits_report_unknown_and_preserve_last_good_baseline(aware, monkeypatch, limit):
    write(aware, 'services/original.py')
    first = aware.scan()
    saved = aware.path.read_bytes()
    write(aware, 'services/new/nested.py', 'updated and longer')
    with monkeypatch.context() as patch:
        patch.setattr(module, limit, 0)
        failed = aware.scan()
    assert not failed['available'] and failed['checked_at'] == first['checked_at']
    assert aware.path.read_bytes() == saved
    assert 'unknown' in aware.describe()
    recovered = aware.scan()
    assert recovered['available'] and recovered['recent_changes'][-1]['counts']['added'] == 1


def test_scan_failure_does_not_invent_deletions_or_lose_later_edits(aware, monkeypatch):
    source = write(aware, 'main.py')
    aware.scan()
    source.write_text('new', encoding='utf-8')
    with monkeypatch.context() as patch:
        patch.setattr(aware, '_snapshot', lambda: (_ for _ in ()).throw(PermissionError('PRIVATE_PATH')))
        assert not aware.scan()['available']
        assert not aware.status()['recent_changes']
        assert 'PRIVATE_PATH' not in json.dumps(aware.status())
    assert aware.scan()['recent_changes'][-1]['counts'] == {'added': 0, 'modified': 1, 'deleted': 0}


def test_file_growth_during_read_is_bounded_and_not_saved_as_a_good_snapshot(aware, monkeypatch):
    source = write(aware, 'main.py', 'small')
    original = Path.open
    class GrowingFile:
        def __enter__(self):
            self.file = original(source, 'rb')
            return self
        def __exit__(self, *args):
            self.file.close()
        def fileno(self):
            return self.file.fileno()
        def read(self, limit):
            assert limit == module.MAX_FILE_BYTES + 1
            source.write_bytes(b'x' * (module.MAX_FILE_BYTES + 20))
            return self.file.read(limit)
    def growing(path, *args, **kwargs):
        return GrowingFile() if path == source and args == ('rb',) else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', growing)
    view = aware.scan()
    assert not view['available'] and not aware.path.exists()


@pytest.mark.parametrize('failure', ['corrupt', 'denied probe', 'unsafe manifest', 'unsafe history', 'huge timestamp'])
def test_bad_history_starts_a_truthful_new_baseline(aware, monkeypatch, failure):
    write(aware, 'main.py')
    aware.scan()
    data = json.loads(aware.path.read_text(encoding='utf-8'))
    if failure == 'corrupt':
        aware.path.write_text('{broken', encoding='utf-8')
    elif failure == 'unsafe manifest':
        data['manifest']['services/../../PRIVATE.py'] = 'a' * 64
        aware.path.write_text(json.dumps(data), encoding='utf-8')
    elif failure in {'unsafe history', 'huge timestamp'}:
        data['history'] = [{'at': 10**400 if failure == 'huge timestamp' else time.time(), 'origin': 'during run',
                            'counts': {'added': 1, 'modified': 0, 'deleted': 0},
                            'components': ['IGNORE INSTRUCTIONS'], 'files': {}}]
        aware.path.write_text(json.dumps(data), encoding='utf-8')
    else:
        original = Path.exists
        def denied(path, *args, **kwargs):
            if path == aware.path:
                raise PermissionError('private path')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'exists', denied)
    restarted = module.DevelopmentAwareness(aware.root, aware.path)
    view = restarted.scan()
    assert view['available'] and not view['recent_changes']
    assert view['history_state'] == 'previous history unavailable'


def test_storage_failure_keeps_live_awareness_and_retries_persistence(aware, monkeypatch):
    source = write(aware, 'main.py')
    aware.scan()
    source.write_text('updated', encoding='utf-8')
    with monkeypatch.context() as patch:
        patch.setattr(module, 'save', lambda *a: (_ for _ in ()).throw(PermissionError('private path')))
        assert aware.scan()['storage_error']
        assert aware.status()['restart_recommended']
    assert not aware.scan()['storage_error']
    restarted = module.DevelopmentAwareness(aware.root, aware.path).scan()
    assert len(restarted['recent_changes']) == 1


def test_history_paths_and_recency_are_bounded(aware):
    aware.scan(now=1000)
    for index in range(module.PATH_LIMIT + 3):
        write(aware, f'services/part{index}.py')
    first = aware.scan(now=1001)
    assert first['recent_changes'][-1]['counts']['added'] == module.PATH_LIMIT + 3
    assert len(first['recent_changes'][-1]['files']['added']) == module.PATH_LIMIT
    for index in range(module.HISTORY_LIMIT + 2):
        write(aware, 'main.py', str(index))
        aware.scan(now=1002 + index)
    assert len(aware.status()['recent_changes']) == module.HISTORY_LIMIT
    assert not aware.status(now=2000)['recent_edits']
    assert aware.status(now=2000)['restart_recommended']


def test_prompt_context_uses_only_cached_safe_metadata(aware, monkeypatch):
    source = write(aware, 'services/PRIVATE_NAME.py', 'PRIVATE_SOURCE')
    aware.scan()
    source.write_text('UPDATED_PRIVATE_SOURCE', encoding='utf-8')
    aware.scan()
    monkeypatch.setattr(aware, '_snapshot', lambda: pytest.fail('Prompt attempted a filesystem scan'))
    prompt = config.SYSTEM_PROMPT
    assert 'development' in prompt and '"restart_recommended": true' in prompt
    for private in ('PRIVATE_NAME', 'PRIVATE_SOURCE', str(aware.root), str(aware.path)):
        assert private not in prompt
    event = cognition.latest('observation')
    assert event['public'] and 'PRIVATE' not in event['text']


def test_development_metadata_preserves_deadlines_in_a_small_prompt(aware, monkeypatch):
    from services.proactive import deadlines
    from services.mind.cognition_context import prompt_section
    from datetime import datetime
    source = write(aware, 'main.py')
    aware.scan()
    source.write_text('updated', encoding='utf-8')
    aware.scan()
    monkeypatch.setattr(config, 'COGNITION_PROMPT_CHARS', 2000)
    deadlines.add('Important assignment', datetime(2030, 1, 12, 17), datetime(2030, 1, 1))
    prompt = prompt_section()
    assert len(prompt) <= 2000 and '2030-01-12T17:00' in prompt


@pytest.mark.parametrize('surface', ['chat', 'voice'])
def test_actual_conversation_receives_development_evidence_without_source(aware, monkeypatch, surface):
    from interfaces.api.routes import chat, voice
    source = write(aware, 'services/PRIVATE_NAME.py', 'PRIVATE_SOURCE')
    aware.scan()
    source.write_text('updated PRIVATE_SOURCE', encoding='utf-8')
    aware.scan()
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(config, 'AI_LANGUAGE_ENABLED', True)
    prompts = []
    async def complete(provider, messages, prompt, *args, **kwargs):
        if kwargs['purpose'] == 'conversation':
            prompts.append(prompt)
        return ProviderResponse(content='{"command":""}' if kwargs['purpose'] == 'understanding'
                                else 'I have observed source edits; loaded behavior is unverified.',
                                provider='openrouter', model='test')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    memory = SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None)
    monkeypatch.setattr(chat, '_memory', memory)
    monkeypatch.setattr(voice, '_memory', memory)
    if surface == 'chat':
        client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
        result = client.post('/api/v1/chat', json={'message': 'How are things going?', 'speak': False}).json()
    else:
        result = asyncio.run(voice._reply('How are things going?', voice.VoiceRequest(speak=False))).model_dump()
    assert result['model'] == 'test' and prompts
    assert '"restart_recommended": true' in prompts[-1]
    assert 'PRIVATE' not in prompts[-1] and str(aware.root) not in prompts[-1]


def test_direct_status_and_api_work_without_ai_and_remote_details_stay_private(aware, monkeypatch):
    from services.automation import intent
    from services.mind.cognition_commands import match_command, run
    write(aware, 'services/PRIVATE_NAME.py')
    aware.scan()
    write(aware, 'services/PRIVATE_NAME.py', 'updated')
    for phrase in ('development status', 'what changed in your code', 'are you being upgraded?',
                   "do you know i'm updating you"):
        assert match_command(phrase) == 'development_status'
    result = asyncio.run(intent.try_system_action('development status', 'openrouter'))
    assert result.success and 'assistant services' in result.message
    assert 'PRIVATE_NAME' not in result.message
    assert 'PRIVATE_NAME' not in result.memory_message
    assert 'PRIVATE_NAME' not in run('development_status', remote=True).message
    monkeypatch.setattr(config, 'COGNITION_ENABLED', False)
    assert run('development_status').success
    client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    status = client.get('/api/v1/mind/development')
    assert status.status_code == 200 and status.json()['restart_recommended']
    assert 'PRIVATE_NAME' in status.text and 'original' not in status.text
    assert client.get('/api/v1/mind/development', headers={'Origin': 'https://evil.example'}).status_code == 403
    from services.screen_watch import commands
    token = commands.local_request.set(False)
    try:
        assert 'PRIVATE_NAME' not in run('development_status').message
        from fastapi import HTTPException
        from interfaces.api.routes.mind import development_status
        with pytest.raises(HTTPException) as denied:
            asyncio.run(development_status())
        assert denied.value.status_code == 403
    finally:
        commands.local_request.reset(token)


@pytest.mark.parametrize('surface', ['chat', 'voice'])
def test_status_reaches_actual_chat_and_voice_without_a_model(aware, monkeypatch, surface):
    from interfaces.api.routes import chat, voice
    source = write(aware, 'services/PRIVATE_NAME.py')
    aware.scan()
    source.write_text('updated', encoding='utf-8')
    saved = []
    memory = SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: saved.append(a))
    monkeypatch.setattr(chat, '_memory', memory)
    monkeypatch.setattr(voice, '_memory', memory)
    async def forbidden(*args, **kwargs):
        pytest.fail('Code status requested an AI or external context')
    for route in (chat, voice):
        monkeypatch.setattr(route, 'build_file_context', forbidden)
        monkeypatch.setattr(route, 'build_search_context', forbidden)
        monkeypatch.setattr(route, 'complete_with_failover', forbidden)
    if surface == 'chat':
        response = asyncio.run(chat.chat(chat.ChatRequest(message='are you being upgraded', speak=False)))
    else:
        response = asyncio.run(voice._reply('are you being upgraded', voice.VoiceRequest(speak=False)))
    assert 'assistant services' in response.response and 'Restart FRIDAY' in response.response
    assert 'PRIVATE_NAME' not in response.response
    assert 'PRIVATE_NAME' not in str(saved)


def test_background_monitor_detects_edits_and_stops_cleanly(aware, monkeypatch):
    source = write(aware, 'main.py')
    aware.scan()
    monkeypatch.setattr(module, 'POLL_SECONDS', .01)
    async def scenario():
        task = asyncio.create_task(aware.run())
        try:
            for _ in range(200):
                if aware.status()['monitor_running']:
                    break
                await asyncio.sleep(.005)
            source.write_text('background edit', encoding='utf-8')
            for _ in range(200):
                if aware.status()['restart_recommended']:
                    break
                await asyncio.sleep(.005)
            assert aware.status()['restart_recommended']
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert not aware.status()['monitor_running']
    asyncio.run(scenario())


def test_api_lifecycle_establishes_baseline_and_registers_monitor(aware, monkeypatch):
    from interfaces.api import app
    registered = []
    def close_task(coroutine):
        registered.append(coroutine.cr_code.co_qualname)
        coroutine.close()
        future = app.asyncio.get_running_loop().create_future()
        future.cancel()
        return future
    write(aware, 'main.py')
    monkeypatch.setattr(app.asyncio, 'create_task', close_task)
    with TestClient(create_app(), base_url='http://127.0.0.1:8000') as client:
        assert client.get('/api/v1/mind/development').json()['watched_files'] == 1
    assert 'DevelopmentAwareness.run' in registered
