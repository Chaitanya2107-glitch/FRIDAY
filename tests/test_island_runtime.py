"""Merged runtime checks use the repository's isolated service fixtures."""
import asyncio
import functools
import json
import time
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from interfaces.api.routes import chat
from services.friday_island_server.config import load_config
from services.friday_island_server.desktop_link import DesktopLink
from services.friday_island_server.runtime import FridayRuntime
from services.friday_island_server.server import Bridge, ORIGINS


def run_async(test):
    @functools.wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


@pytest.fixture
def island_config(tmp_path, monkeypatch):
    path = tmp_path / 'island.json'
    monkeypatch.setenv('FRIDAY_ISLAND_CONFIG', str(path))
    return path, load_config(path)


@pytest.fixture
def desktop(monkeypatch):
    from services.friday_island_server import desktop_link
    link = DesktopLink()
    monkeypatch.setattr(desktop_link, 'desktop', link)
    return link


@run_async
async def test_actual_note_uses_existing_store_and_chat_history(desktop):
    from services.memory import notes
    runtime = FridayRuntime()
    result = await runtime.command('note buy a charger', object())
    assert result['ok'] and 'charger' in str(notes.load())
    history = (await runtime.history())['items']
    assert any('charger' in row['content'] for row in history)


@run_async
async def test_local_authority_and_private_metadata_restore_on_error(monkeypatch, desktop):
    from services.automation.intent import remote_request, telegram_owner, skip_confirmation
    from services.screen_watch.commands import local_request
    variables = [remote_request, telegram_owner, skip_confirmation, local_request]
    tokens = [var.set(value) for var, value in zip(variables, [True, True, True, False])]
    async def reply(request):
        assert [var.get() for var in variables] == [False, False, False, True]
        return chat.ChatResponse(response='private response', private=True, awaiting_reply=True,
                                 action_success=False, provider='local', model='test', tokens_used=0,
                                 automation_job='job1')
    monkeypatch.setattr(chat, 'chat', reply)
    try:
        result = await FridayRuntime().command('private question', object())
        assert result['private'] and result['awaiting_reply'] and not result['ok']
        assert result['automation_job'] == 'job1'
        assert [var.get() for var in variables] == [True, True, True, False]
        async def fail(request):
            raise RuntimeError('test failure')
        monkeypatch.setattr(chat, 'chat', fail)
        with pytest.raises(RuntimeError):
            await FridayRuntime().command('hello', object())
        assert [var.get() for var in variables] == [True, True, True, False]
    finally:
        for var, token in zip(variables, tokens): var.reset(token)


@run_async
async def test_desktop_cleanup_cannot_mask_submitted_action(monkeypatch, desktop):
    desktop.exchange('controller', {})
    original = desktop.enqueue
    def enqueue(action, value=''):
        if action == 'typed_done': raise ValueError('queue full')
        return original(action, value)
    monkeypatch.setattr(desktop, 'enqueue', enqueue)
    async def reply(request):
        return chat.ChatResponse(response='Done', provider='local', model='test', tokens_used=0)
    monkeypatch.setattr(chat, 'chat', reply)
    async def acknowledge():
        while True:
            commands = desktop.exchange('controller', {})
            desktop.exchange('controller', {}, [row['id'] for row in commands])
            await asyncio.sleep(.01)
    consumer = asyncio.create_task(acknowledge())
    try:
        assert (await FridayRuntime().command('hello', object()))['text'] == 'Done'
    finally:
        consumer.cancel(); await asyncio.gather(consumer, return_exceptions=True)


@run_async
async def test_keyboard_is_socket_bound_one_use_and_never_accepts_inbound_steps(monkeypatch, desktop):
    async def reply(request):
        return chat.ChatResponse(response='Typing', keyboard=[{'text': 'safe test'}],
                                 provider='local', model='test', tokens_used=0)
    monkeypatch.setattr(chat, 'chat', reply)
    runtime, owner, other = FridayRuntime(), object(), object()
    target = {'hwnd': 123, 'pid': 456, 'captured_at': time.time()}
    result = await runtime.command('type safe test', owner, target)
    token = result['keyboard_token']
    assert 'keyboard' not in result
    assert result['private']
    with pytest.raises(ValueError, match='another connection'):
        await runtime.apply_keyboard(token, other)
    seen = []
    monkeypatch.setattr(runtime, '_type', lambda item, run: seen.append(item['steps']))
    await runtime.apply_keyboard(token, owner)
    assert seen == [[{'text': 'safe test'}]]
    with pytest.raises(ValueError): await runtime.apply_keyboard(token, owner)
    result = await runtime.command('type safe test', owner, target)
    runtime.disconnect(owner)
    with pytest.raises(ValueError): await runtime.apply_keyboard(result['keyboard_token'], owner)


def test_keyboard_refuses_a_different_foreground_process(monkeypatch):
    import win32gui, win32process, psutil
    monkeypatch.setattr(win32gui, 'GetForegroundWindow', lambda: 12)
    monkeypatch.setattr(win32process, 'GetWindowThreadProcessId', lambda hwnd: (1, 99))
    monkeypatch.setattr(psutil, 'Process', lambda pid: SimpleNamespace(create_time=lambda: 1))
    with pytest.raises(ValueError, match='active window changed'):
        FridayRuntime._type({'target': {'hwnd': 12, 'pid': 100, 'captured_at': 2}, 'steps': []},
                            lambda steps: pytest.fail('must not type'))


@run_async
async def test_stop_tasks_remains_responsive_during_an_active_turn(monkeypatch, desktop):
    from services.browser.service import automation
    from services.computer.agent import computer_agent
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def answer(request):
        started.set(); await release.wait()
        return chat.ChatResponse(response='Finished', provider='local', model='test', tokens_used=0)
    async def stop(message, provider): calls.append(message)
    monkeypatch.setattr(chat, 'chat', answer)
    monkeypatch.setattr(automation, 'handle', stop)
    monkeypatch.setattr(computer_agent, 'cancel', lambda: calls.append('computer cancel'))
    runtime = FridayRuntime()
    task = asyncio.create_task(runtime.command('hello', object()))
    try:
        await started.wait()
        result = await asyncio.wait_for(runtime.action('automation_stop'), 1)
        assert result['ok'] and calls == ['browser stop', 'computer cancel']
        assert not task.done()
    finally:
        release.set(); await task


def test_project_import_preserves_conflicts_and_unifies_matching_folders(tmp_path):
    from services import customization
    from services.friday_island_server.config import IslandConfig, Project
    from services.friday_island_server.projects import import_profiles
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir(); second.mkdir()
    snapshot = customization.snapshot('projects')
    customization.change('projects', original=None, name='work', value={'path': str(first)}, revision=snapshot['revision'])
    config = IslandConfig(projects=[Project(id='conflict', name='work', path=str(second)),
                                    Project(id='matched', name='Same folder', path=str(first))])
    result = import_profiles(config)
    assert result['conflicts'] == ['work']
    canonical = customization.snapshot('projects')['items']
    assert next(row for row in canonical if row['name'] == 'work')['value']['path'] == str(first.resolve())
    assert next(row for row in result['items'] if row['name'] == 'work')['native_id'] == 'matched'
    assert len(config.projects) == 2


def test_desktop_claims_are_one_time_leased_and_single_owner(desktop):
    desktop.exchange('owner1', {})
    desktop.enqueue('listen')
    with pytest.raises(ValueError): desktop.exchange('owner2', {})
    claimed = desktop.exchange('owner1', {})[0]
    assert claimed['action'] == 'listen' and not desktop.acknowledged(claimed['id'])
    desktop.exchange('owner1', {}, [claimed['id']])
    assert desktop.acknowledged(claimed['id'])
    assert desktop.exchange('owner1', {}) == []
    with pytest.raises(ValueError): desktop.enqueue('shell')
    desktop.seen = 0
    with pytest.raises(ValueError): desktop.enqueue('listen')
    assert desktop.exchange('owner2', {}) == []


@run_async
async def test_failed_readiness_cancels_late_turn_and_releases_conversation(monkeypatch, desktop):
    from interfaces.api.routes import voice
    desktop.exchange('controller', {'listening': True})
    original = desktop.enqueue
    actions = []
    def enqueue(action, value=''):
        actions.append(action)
        command_id = original(action, value)
        if action == 'typed':
            desktop.completed.append(command_id)
        return command_id
    async def failed_stop(discard): raise RuntimeError('recording control failed')
    async def forbidden(request): pytest.fail('assistant action must not start')
    monkeypatch.setattr(desktop, 'enqueue', enqueue)
    monkeypatch.setattr(voice, 'stop_listening', failed_stop)
    monkeypatch.setattr(chat, 'chat', forbidden)
    with pytest.raises(RuntimeError, match='recording control failed'):
        await FridayRuntime().command('hello', object())
    assert actions == ['typed', 'typed_done']
    assert [row['action'] for row in desktop.pending] == ['typed_done']


def test_events_are_bounded_paginated_and_exclude_private(monkeypatch):
    from collections import deque
    from services.friday_island_server import events
    monkeypatch.setattr(events, '_events', deque(maxlen=80))
    monkeypatch.setattr(events, '_sequence', 0)
    events.publish('response', 'private', private=True)
    for index in range(15): events.publish('notification', str(index))
    first = events.snapshot(0)
    assert first['last'] == 6 and len(first['events']) == 6
    second = events.snapshot(first['last'])
    assert second['events'][0]['id'] == 7
    assert events.snapshot()['events'] == []


def test_transient_toasts_do_not_become_persistent_island_events(monkeypatch):
    from services.reminders import service
    from services.friday_island_server import events
    monkeypatch.setattr(service, '_show_toast', lambda *args, **kwargs: True)
    calls = []
    monkeypatch.setattr(events, 'publish', lambda *args, **kwargs: calls.append(args))
    assert service.show_toast('FRIDAY', 'Opened', transient=True)
    assert calls == []
    assert service.show_toast('FRIDAY', 'Reminder')
    assert calls == [('notification', 'Reminder')]


@run_async
async def test_stop_controls_bypass_long_command_and_rotation_revokes_events(island_config):
    path, config = island_config
    started, release = asyncio.Event(), asyncio.Event()
    actions = []
    class Runtime:
        async def command(self, text, owner, target):
            started.set(); await release.wait(); return {'ok': True, 'text': 'Done'}
        async def snapshot(self, since):
            return {'epoch': 'test', 'last': 0, 'events': []}
        async def action(self, action, value):
            actions.append(action); return {'ok': True, 'text': 'Stopped'}
        def disconnect(self, owner): pass
    bridge = Bridge(path, runtime=Runtime())
    async with serve(bridge.handle, '127.0.0.1', 0, origins=ORIGINS) as server:
        async with connect(f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}', origin=ORIGINS[0]) as ws:
            await ws.send(json.dumps({'v': 1, 'type': 'handshake', 'id': 'hello', 'token': config.connection.token}))
            while json.loads(await ws.recv())['type'] != 'runtime_state': pass
            await ws.send(json.dumps({'v': 1, 'type': 'command', 'id': 'work', 'text': 'hello'}))
            await asyncio.wait_for(started.wait(), 2)
            await ws.send(json.dumps({'v': 1, 'type': 'runtime_action', 'id': 'stop', 'action': 'speech_stop'}))
            while (frame := json.loads(await ws.recv())).get('id') != 'stop': pass
            assert frame['ok'] and actions == ['speech_stop']
            config.connection.token = 'a' * 64
            path.write_text(config.model_dump_json(), encoding='utf-8')
            release.set()
            with pytest.raises(ConnectionClosed):
                while True: await asyncio.wait_for(ws.recv(), 3)


def test_native_controller_route_authentication_and_no_arbitrary_actions(island_config, desktop, monkeypatch):
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    client = TestClient(create_app(), base_url='http://127.0.0.1')
    body = {'owner': 'x' * 24, 'state': {}}
    assert client.post('/api/v1/island/desktop', json=body).status_code == 403
    headers = {'X-Friday-Island': island_config[1].connection.token}
    assert client.post('/api/v1/island/desktop', headers=headers, json=body).status_code == 200
    assert client.post('/api/v1/island/desktop', headers={**headers, 'Origin': 'https://evil.test'}, json=body).status_code == 403
    assert client.post('/api/v1/island/desktop', headers=headers, json={**body, 'state': {'shell': 'x'}}).status_code == 422
    from services.friday_island_server import events
    published = []
    monkeypatch.setattr(events, 'connected', lambda: True)
    monkeypatch.setattr(events, 'publish', lambda *args, **kwargs: published.append((args, kwargs)))
    response = client.post('/api/v1/island/event', headers=headers, json={'kind': 'response', 'text': 'Opened', 'transient': True})
    assert response.status_code == 200 and response.json()['accepted']
    assert published == [(('response', 'Opened'), {'awaiting_reply': False, 'transient': True})]
    assert client.post('/api/v1/island/event', json={'kind': 'response', 'text': 'Opened'}).status_code == 403


@run_async
async def test_integrated_transport_rebinds_and_reports_readiness(island_config, monkeypatch):
    import socket
    from services.friday_island_server.server import run_integrated_bridge, transport_state
    path, config = island_config
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]
    async def snapshot(self, since): return {'epoch': 'test', 'last': 0, 'events': []}
    monkeypatch.setattr(FridayRuntime, 'snapshot', snapshot)
    config.connection.port = free_port()
    path.write_text(config.model_dump_json(), encoding='utf-8')
    task = asyncio.create_task(run_integrated_bridge())
    reserved = None
    async def until(predicate):
        # Real Windows socket release can lag while the native build is running.
        async with asyncio.timeout(30):
            while not predicate():
                await asyncio.sleep(.05)
    try:
        await until(lambda: transport_state['ready'] and transport_state['port'] == config.connection.port)
        assert transport_state['ready'] and transport_state['port'] == config.connection.port
        async with connect(f'ws://127.0.0.1:{config.connection.port}', origin=ORIGINS[0]) as ws:
            await ws.send(json.dumps({'v': 1, 'type': 'handshake', 'id': 'hello', 'token': config.connection.token}))
            while (frame := json.loads(await ws.recv()))['type'] != 'status': pass
            assert frame['integrated']
        reserved = socket.socket()
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            reserved.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reserved.bind(('127.0.0.1', 0))
        reserved.listen()
        config.connection.port = reserved.getsockname()[1]
        path.write_text(config.model_dump_json(), encoding='utf-8')
        await until(lambda: not transport_state['ready'] and transport_state['error'] == 'OSError')
        reserved.close()
        await until(lambda: transport_state['ready'] and transport_state['port'] == config.connection.port)
        assert transport_state['ready'] and transport_state['port'] == config.connection.port
    finally:
        if reserved: reserved.close()
        task.cancel(); await asyncio.gather(task, return_exceptions=True)
    assert not transport_state['ready']
