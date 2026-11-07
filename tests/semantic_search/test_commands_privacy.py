import asyncio
import json
import logging
from pathlib import Path
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from services import plugin_runtime
from services.automation import intent
from services.friday_island_server.http import create_router
from tests.semantic_search.conftest import wait_for

CANARY = 'DOCUMENT_BODY_CANARY_q7zx82'


def test_plain_commands_cards_private_content_and_actions(indexed, monkeypatch, corpus):
    path = corpus / 'private_note.txt'
    path.write_text(f'An aardvark observation. {CANARY} appears in this synthetic document.', encoding='utf-8')
    indexed.indexer.scan()
    reply = indexed.command(indexed.match_command('find aardvark'))
    assert CANARY in reply['text']
    event = indexed.api.bus.recent('ui.card')[-1]
    assert CANARY not in json.dumps(event)
    payload = event['payload']
    assert len(payload['actions']) <= 6
    body = indexed.content({'query': {'ref': payload['content_ref']}})['body']
    assert CANARY in body
    opened = []
    monkeypatch.setattr('os.startfile', opened.append)
    assert indexed.command(indexed.match_command('open result 1'))['ok']
    assert opened == [str(path)]
    selected = payload['actions'][0]['payload']
    assert indexed.action('select', selected)['ok']
    actions = indexed.api.bus.recent('ui.card')[-1]['payload']['actions']
    assert [a['label'] for a in actions] == ['Open file', 'Open containing folder', 'Copy path']
    assert indexed.action('folder', selected)['ok'] and opened[-1] == str(corpus)
    from services.automation import clipboard
    copied = []
    monkeypatch.setattr(clipboard, 'set_text', copied.append)
    assert indexed.action('copy', selected)['ok'] and copied == [str(path)]
    (corpus / '.nosearch').touch()
    assert not indexed.action('open', selected)['ok']


def test_more_cards_and_confirmation_scoping(indexed):
    hits = indexed.search('the', k=5)
    # Use actual indexed hits, independent of relevance thresholds for the broad query.
    if len(hits) < 5:
        hits = [indexed.search(q)[0] for q in ['Carnot', 'lease', 'photosynthesis', 'budget', 'Mars']]
    token = indexed.remember(hits)
    indexed.card(token)
    actions = indexed.api.bus.recent('ui.card')[-1]['payload']['actions']
    assert len(actions) == 4 and actions[-1]['id'] == 'more'
    assert indexed.action('more', {'token': token})['ok']
    assert indexed.api.bus.recent('ui.card')[-1]['payload']['result_start'] == 3
    assert not indexed.delete()['ok']
    assert indexed.command(indexed.match_command('delete search index'))['ok']
    assert not indexed.delete('wrong-confirmation')['ok']
    assert indexed.command(indexed.match_command('cancel delete search index'))['ok']
    assert not indexed.delete()['ok']


def test_delete_clears_data_without_touching_documents_or_model(host, corpus):
    service = host.get_service('semantic_search')
    host.command(f'index folder "{corpus}"')
    wait_for(lambda: service.store.stats()['vectors'] == 22)
    (service.api.data_dir / 'models').mkdir()
    marker = service.api.data_dir / 'models' / 'keep.txt'
    marker.write_text('model fixture')
    assert host.command('delete search index')['ok']
    assert host.command('confirm delete search index')['ok']
    wait_for(lambda: service.store.stats()['chunks'] == 0 and not service.indexer.scanning)
    assert len(list(corpus.iterdir())) == 20 and marker.exists()
    assert service.indexer.roots() == []
    assert not service.search('quantum')
    assert b'Quantum entanglement' not in service.store.path.read_bytes()


@pytest.mark.parametrize('text', ['find quantum', 'search my notes for quantum', 'find the pdf about quantum',
    'what did my notes say about quantum', 'find bread and butter', 'open result two'])
def test_whole_string_spoken_commands(host, text):
    service = host.get_service('semantic_search')
    assert service.match_command(text)
    assert service.match_command('hey friday, ' + text + ' please!')
    assert not service.match_command('something ' + text)


def test_privacy_errors_logs_events_and_authenticated_bridge(host, corpus, caplog, monkeypatch):
    service = host.get_service('semantic_search')
    path = corpus / 'canary.txt'
    path.write_text('An aardvark. ' + CANARY)
    caplog.set_level(logging.DEBUG)
    host.command(f'index folder "{corpus}"')
    wait_for(lambda: service.store.known().get(str(path), {}).get('status') == 'ready')
    reply = host.command('find aardvark')
    assert CANARY in reply['text']
    safe = host.bus.recent('ui.card')[-1]['payload']
    token = 'a' * 64
    app = FastAPI()
    app.include_router(create_router(lambda: host, lambda: SimpleNamespace(connection=SimpleNamespace(token=token))))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        endpoint = '/api/plugins/semantic_search/results?ref=' + safe['content_ref']
        assert client.get(endpoint).status_code == 401
        response = client.get(endpoint, headers={'X-Friday-Token': token})
        assert CANARY in response.json()['body']
    assert CANARY not in json.dumps(host.bus.recent()) and CANARY not in caplog.text
    import pypdf
    def failure(path):
        logging.getLogger('pypdf.created_during_extraction').warning(CANARY)
        raise ValueError(CANARY)
    monkeypatch.setattr(pypdf, 'PdfReader', lambda *a, **kw: failure(a[0]))
    (corpus / 'broken.pdf').write_text(CANARY)
    host.command('reindex')
    wait_for(lambda: service.store.known().get(str(corpus / 'broken.pdf'), {}).get('status') == 'error')
    assert CANARY not in caplog.text and CANARY not in json.dumps(host.bus.recent())


def test_chat_voice_and_intent_bypass_cloud_and_history(host, corpus, monkeypatch, caplog):
    from interfaces.api.routes import chat, voice
    service = host.get_service('semantic_search')
    (corpus / 'canary.txt').write_text('An aardvark. ' + CANARY)
    host.command(f'index folder "{corpus}"')
    wait_for(lambda: service.store.known().get(str(corpus / 'canary.txt'), {}).get('status') == 'ready')
    monkeypatch.setattr(plugin_runtime, '_manager', host)
    host.builtin_matcher = plugin_runtime.builtin_matches
    async def forbidden(*a, **kw):
        pytest.fail('Private search entered cloud context or provider')
    monkeypatch.setattr(chat, 'build_file_context', forbidden)
    monkeypatch.setattr(chat, 'build_search_context', forbidden)
    monkeypatch.setattr(voice, 'build_file_context', forbidden)
    monkeypatch.setattr(voice, 'build_search_context', forbidden)
    monkeypatch.setattr(chat, 'complete_with_failover', forbidden)
    monkeypatch.setattr(voice, 'complete_with_failover', forbidden)
    monkeypatch.setattr(chat._memory, 'save_message', lambda *a: pytest.fail('Private document stored in history'))
    monkeypatch.setattr(chat, '_speak_in_background', lambda *a, **kw: pytest.fail('Private document reached TTS'))
    monkeypatch.setattr(voice, '_speak_in_background', lambda *a, **kw: pytest.fail('Private document reached TTS'))
    async def run():
        reply = await chat.chat(chat.ChatRequest(message='what did my notes say about aardvark', speak=True))
        assert reply.private and reply.provider == 'local' and CANARY in reply.response
        spoken = await voice._reply('find aardvark', voice.VoiceRequest(speak=True))
        assert spoken.private and CANARY in spoken.response
        action = await intent.try_system_action('find aardvark', 'openrouter')
        assert CANARY in action.message and CANARY not in action.memory_message
        remote = intent.remote_request.set(True)
        try:
            blocked = await chat.chat(chat.ChatRequest(message='find aardvark'))
            assert not blocked.action_success and CANARY not in blocked.response
        finally:
            intent.remote_request.reset(remote)
    asyncio.run(run())
    assert CANARY not in caplog.text and CANARY not in json.dumps(host.bus.recent())
    assert host.command('find aardvark')['ok']
