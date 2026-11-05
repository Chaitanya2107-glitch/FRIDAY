"""Explicit focus, original reports, source revisions and channel boundaries."""

import asyncio
from datetime import datetime, timedelta
import json

import pytest

from core.config import config
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition, cognition
from services.mind.commitment_topics import CommitmentTopics
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
from services.mind.working_memory import WorkingMemory, MAX_CHARS
from services.mind.workspace import Workspace
from providers.base_provider import ProviderResponse

NOW = datetime(2026, 11, 5, 12)


@pytest.fixture
def memory(tmp_path):
    store = Cognition(tmp_path / 'mind.db')
    return WorkingMemory(store), BrainMemory(store), Workspace(store)


def commitment(store, episodes, *, subject='robotics exam', phrase='November 8', supersedes=()):
    text = f'My {subject} was postponed to {phrase}' if supersedes else f'My {subject} is on {phrase}'
    noted = NOW + timedelta(minutes=1) if supersedes else NOW
    ident = episodes.remember(text, now=noted)
    temporal = TemporalMemory(store)
    known = {**episodes.evidence(), **temporal.evidence()}
    update = TemporalUpdate(source=f'owner_episode:{ident}', quote=text, subject=subject,
                            status='planned', date_phrase=phrase, start=None, end=None, supersedes=list(supersedes))
    with temporal._db() as db:
        temporal.save(db, temporal.resolve([update], known), noted, known)
    return next(row for row in temporal.evidence().values() if row['subject'] == subject)


def test_explicit_task_and_goal_are_recalled_across_restart_without_inference(memory):
    view, episodes, workspace = memory
    goal = workspace.add_goal('Study robotics', 'high')
    task = workspace.start_task('Revise transforms', goal)
    workspace.plan(task, ['Read notes', 'Solve problems'])
    workspace.focus('goal', goal)
    workspace.focus('task', task)
    episodes.remember('I need to practise coordinate transforms.', now=NOW)
    snapshot = WorkingMemory(Cognition(view.store.path)).snapshot()
    assert snapshot['available'] and snapshot['scope'] == 'local'
    selected = {row['id']: row for row in snapshot['focus']}
    assert selected[f'task:{task}']['next_step'] == 'Read notes'
    assert selected[f'goal:{goal}']['priority'] == 3
    assert snapshot['recent_reports'][0]['text'] == 'I need to practise coordinate transforms.'
    assert 'not independent completion proof' in selected[f'task:{task}']['meaning']


def test_no_selection_does_not_invent_a_topic_from_recent_reports(memory):
    view, episodes, _ = memory
    episodes.remember('I was reading a robotics paper yesterday.', now=NOW)
    result = view.snapshot()
    assert not result['focus'] and result['commitment'] is None
    assert 'not an inferred active topic' in result['meaning']
    assert 'No task or commitment is explicitly selected' in view.describe()


def test_private_and_remote_reports_have_disjoint_scopes(memory):
    view, episodes, workspace = memory
    episodes.remember('LOCAL-ONLY REPORT', channel='voice', now=NOW)
    episodes.remember('REMOTE REPORT', channel='telegram', now=NOW)
    task = workspace.start_task('PRIVATE SELECTED TASK')
    workspace.focus('task', task)
    local, remote = view.snapshot(), view.snapshot(channel='telegram')
    assert 'REMOTE REPORT' not in json.dumps(local)
    assert 'LOCAL-ONLY REPORT' not in json.dumps(remote)
    assert 'PRIVATE SELECTED TASK' not in json.dumps(remote)
    assert remote['focus'] == [] and remote['commitment'] is None
    assert remote['recent_reports'][0]['text'] == 'REMOTE REPORT'


def test_task_revision_invalidates_prepared_context(memory):
    view, _, workspace = memory
    task = workspace.start_task('Prepare notes')
    workspace.focus('task', task)
    snapshot = view.snapshot()
    assert view.revalidate(snapshot)
    workspace.plan(task, ['Use revised notes'])
    assert view.revalidate(snapshot) is None


def test_scope_change_and_forgotten_sources_invalidate_context(memory):
    view, episodes, _ = memory
    episodes.remember('Original owner report', now=NOW)
    snapshot = view.snapshot()
    assert view.revalidate(snapshot, channel='telegram') is None
    view.store.clear()
    assert view.revalidate(snapshot) is None
    assert view.snapshot()['recent_reports'] == []


def test_hidden_or_revised_report_is_not_recalled(memory):
    view, episodes, _ = memory
    ident = episodes.remember('An obsolete report', now=NOW)
    snapshot = view.snapshot()
    with episodes._db() as db:
        db.execute('UPDATE owner_episodes SET recall_withheld=1 WHERE id=?', (ident,))
    assert view.revalidate(snapshot) is None
    assert not view.snapshot()['recent_reports']


def test_commitment_requires_exact_saved_version_and_unexpired_reference(memory):
    view, episodes, _ = memory
    original = commitment(view.store, episodes)
    CommitmentTopics(view.store).remember(original)
    snapshot = view.snapshot()
    assert snapshot['commitment']['subject'] == 'robotics exam'
    assert snapshot['commitment']['start'] == '2026-11-08'
    replacement = commitment(view.store, episodes, phrase='November 10', supersedes=[original['id']])
    assert replacement['start'] == '2026-11-10'
    assert view.revalidate(snapshot) is None
    assert view.snapshot()['commitment'] is None
    assert 'November 8' not in json.dumps(view.snapshot()['recent_reports'])


def test_expired_topic_does_not_reappear(memory):
    view, episodes, workspace = memory
    expected = commitment(view.store, episodes)
    CommitmentTopics(view.store).remember(expected)
    snapshot = view.snapshot()
    with workspace._db() as db:
        db.execute("UPDATE workspace_reference_context SET expires=0 WHERE kind='commitment_topic'")
    assert view.revalidate(snapshot) is None
    assert view.snapshot()['commitment'] is None


def test_working_context_is_bounded_and_marks_incomplete_sources(memory):
    view, episodes, _ = memory
    for index in range(4):
        episodes.remember(f'Owner report {index}: ' + 'x' * 3000, now=NOW + timedelta(seconds=index))
    snapshot = view.snapshot()
    assert len(json.dumps(snapshot, ensure_ascii=False)) <= MAX_CHARS + 100
    assert snapshot['recent_reports'] and all(row['excerpt_truncated'] for row in snapshot['recent_reports'])


def test_current_credentials_are_redacted_even_from_old_stored_reports(memory, monkeypatch):
    view, episodes, _ = memory
    episodes.remember('An old token was secret-value-for-test', now=NOW)
    monkeypatch.setattr(config, 'OPENAI_API_KEY', 'secret-value-for-test')
    snapshot = view.snapshot()
    assert 'secret-value-for-test' not in json.dumps(snapshot)
    assert '[credential removed]' in snapshot['recent_reports'][0]['text']


def test_disabled_cognition_does_not_read_or_return_private_context(memory, monkeypatch):
    view, episodes, _ = memory
    episodes.remember('Private owner report', now=NOW)
    monkeypatch.setattr(config, 'COGNITION_ENABLED', False)
    assert view.snapshot() == {'available': False, 'reason': 'cognition_disabled'}


def test_original_source_edit_invalidates_snapshot(memory):
    view, episodes, _ = memory
    ident = episodes.remember('Original statement', now=NOW)
    snapshot = view.snapshot()
    with episodes._db() as db:
        db.execute('UPDATE owner_episodes SET text=? WHERE id=?', ('Corrected statement', ident))
    assert view.revalidate(snapshot) is None


def test_status_read_does_not_clear_the_selected_commitment(monkeypatch):
    from services.automation import intent
    from services.mind import commitment_topics
    episodes = BrainMemory(cognition)
    expected = commitment(cognition, episodes)
    commitment_topics.topics.remember(expected)
    result = asyncio.run(intent.try_system_action('working memory status', 'unavailable-provider'))
    assert result.success and 'robotics exam' in result.message
    assert not result.repeatable
    assert WorkingMemory(cognition).snapshot()['commitment'] is not None


@pytest.mark.parametrize('surface', ['chat', 'voice'])
def test_real_status_routes_are_local_and_have_no_model_or_retrieval_calls(monkeypatch, surface):
    from interfaces.api.routes import chat, voice
    from services.mind import wording

    async def forbidden(*args, **kwargs):
        pytest.fail('Working memory inspection attempted model or retrieval')

    for module in (chat, voice):
        for name in ('build_search_context', 'build_file_context', 'complete_with_failover'):
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(wording, 'enhance', forbidden)
    result = (asyncio.run(chat.chat(chat.ChatRequest(message='working memory status', speak=False))) if surface == 'chat'
              else asyncio.run(voice._reply('working memory status', voice.VoiceRequest(speak=False))))
    assert 'Working memory' in result.response and result.tokens_used == 0
    assert not result.keyboard


def test_working_memory_api_is_local_only():
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    local = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    assert local.get('/api/v1/mind/working-memory').status_code == 200
    remote = TestClient(create_app(), base_url='http://127.0.0.1:8000', client=('192.0.2.5', 50000))
    assert remote.get('/api/v1/mind/working-memory').status_code == 403


def test_conversation_receives_only_revalidated_selected_work(monkeypatch):
    from services.mind import language
    workspace = Workspace(cognition)
    task = workspace.start_task('SELECTED ROBOTICS WORK')
    workspace.plan(task, ['Read the coordinate notes'])
    workspace.focus('task', task)
    calls = []

    async def complete(*args, **kwargs):
        calls.append((args, kwargs))
        return ProviderResponse(content='We can review the selected notes.', provider='openrouter', model='test-model')

    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(language.answer('How should we prepare?', 'openrouter', [], 100))
    prompt = calls[0][0][2]
    assert 'Source-backed working memory' in prompt and 'SELECTED ROBOTICS WORK' in prompt
    assert 'Read the coordinate notes' in prompt
    assert 'not alone identify the current topic' in prompt
    assert calls[0][1]['purpose'] == 'conversation' and 'tools' not in calls[0][1]
    assert result.content == 'We can review the selected notes.'


def test_source_change_during_conversation_withholds_stale_reply(monkeypatch):
    from services.mind import language
    workspace = Workspace(cognition)
    task = workspace.start_task('A saved task')
    workspace.focus('task', task)

    async def complete(*args, **kwargs):
        workspace.plan(task, ['The corrected step'])
        return ProviderResponse(content='OLD PRIVATE CONTEXT ANSWER', provider='openrouter', model='test-model', tokens_used=17)

    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(language.answer('What next?', 'openrouter', [], 100))
    assert 'OLD PRIVATE' not in result.content and 'context changed' in result.content
    assert result.tokens_used == 17  # Account for the actual provider request even when its output is withheld.


def test_changed_selected_context_is_withheld_before_provider_handoff(monkeypatch):
    from services.mind import language, working_memory
    workspace = Workspace(cognition)
    task = workspace.start_task('A selected source')
    workspace.focus('task', task)
    monkeypatch.setattr(working_memory.working_memory, 'revalidate', lambda *a, **kw: None)

    async def forbidden(*args, **kwargs):
        pytest.fail('Stale working context reached a provider')

    monkeypatch.setattr('providers.failover.complete_with_failover', forbidden)
    result = asyncio.run(language.answer('What next?', 'openrouter', [], 100))
    assert result.provider == 'local' and 'context changed' in result.content and result.tokens_used == 0


def test_forgetting_during_conversation_withholds_private_reply(monkeypatch):
    from services.mind import language
    workspace = Workspace(cognition)
    task = workspace.start_task('A private task')
    workspace.focus('task', task)

    async def complete(*args, **kwargs):
        cognition.clear()
        return ProviderResponse(content='FORGOTTEN PRIVATE ANSWER', provider='openrouter', model='test-model')

    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(language.answer('What next?', 'openrouter', [], 100))
    assert 'FORGOTTEN PRIVATE' not in result.content and 'context changed' in result.content


def test_remote_flag_alone_cannot_enable_local_working_context(monkeypatch):
    from services.mind import language
    from services.automation import intent
    episodes = BrainMemory(cognition)
    episodes.remember('LOCAL PRIVATE REPORT', channel='chat', now=NOW)
    seen = []

    async def complete(*args, **kwargs):
        seen.append(args[2])
        return ProviderResponse(content='Remote reply.', provider='openrouter', model='test-model')

    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    token = intent.remote_request.set(True)
    try:
        result = asyncio.run(language.answer('What did I say?', 'openrouter', [], 100))
    finally:
        intent.remote_request.reset(token)
    assert result.content == 'Remote reply.'
    assert 'Source-backed working memory' not in seen[0]
    assert 'LOCAL PRIVATE REPORT' not in seen[0]


def test_unselected_working_context_does_not_invalidate_an_unrelated_answer(monkeypatch):
    from services.mind import language
    episodes = BrainMemory(cognition)

    async def complete(*args, **kwargs):
        assert 'Source-backed working memory' not in args[2]
        episodes.remember('An unrelated new owner report.', now=NOW)
        return ProviderResponse(content='Two plus two is four.', provider='openrouter', model='test-model')

    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(language.answer('What is two plus two?', 'openrouter', [], 100))
    assert result.content == 'Two plus two is four.'
