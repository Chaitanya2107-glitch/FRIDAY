"""Current commitment questions stay local, versioned and read-only."""
import asyncio
import contextvars
import json
import sqlite3
from datetime import timedelta

import pytest

from core.config import config
from services.mind.temporal_memory import TemporalUpdate
from test_dialogue_followups import conversation, say, NOW


def test_named_commitment_then_short_followup_uses_the_same_report(conversation):
    result = say('When is my robotics exam?')
    assert result is not None and result.success and '2026-10-24' in result.message
    assert 'robotics exam' in say('When is it again?').message
    assert conversation[3] == []


@pytest.fixture
def topic(conversation, monkeypatch):
    from services.mind import commitment_topics
    monkeypatch.setattr(commitment_topics, 'clock', lambda: NOW)
    return conversation


def revision(topic, *, phrase='November 3', status='planned'):
    _, episodes, temporal, _ = topic
    target = next(row for row in temporal.evidence().values() if row['subject'] == 'robotics exam')
    text = f'My robotics exam was postponed to {phrase}'
    source = episodes.remember(text, now=NOW)
    known = {**temporal.evidence(), **episodes.evidence()}
    value = TemporalUpdate(source=f'owner_episode:{source}', quote=text, subject='robotics exam',
        status=status, date_phrase=phrase, start=None, end=None, supersedes=[target['id']])
    with temporal._db() as db:
        temporal.save(db, temporal.resolve([value], known), NOW, known)


def test_countdown_switch_and_midnight_share_one_topic(topic, monkeypatch):
    from services.mind import commitment_topics
    assert say('When is my robotics exam?').success
    assert '2 days' in say('How many days left?').message
    assert 'maths exam' in say('What about my maths exam?').message
    assert '4 days' in say('How many days until it?').message
    monkeypatch.setattr(commitment_topics, 'clock', lambda: NOW + timedelta(days=1))
    assert '3 days' in say('How many days left?').message
    assert topic[3] == []


def test_chat_and_voice_topic_questions_bypass_search_models_and_learning(topic, monkeypatch):
    from interfaces.api.routes import chat, voice
    async def forbidden(*args, **kwargs):
        pytest.fail('A deterministic topic question reached search or a model')
    for module in (chat, voice):
        monkeypatch.setattr(module, 'build_file_context', forbidden)
        monkeypatch.setattr(module, 'build_search_context', forbidden)
        monkeypatch.setattr(module.humour, 'hear', lambda *a: pytest.fail('Topic question reached learning'))
        monkeypatch.setattr(module.talk, 'hear', lambda *a: pytest.fail('Topic question consumed an optional answer'))
    monkeypatch.setattr('providers.failover.complete_with_failover', forbidden)
    result = asyncio.run(chat.chat(chat.ChatRequest(message='When is my robotics exam?')))
    assert result.action_success and not result.awaiting_reply
    result = asyncio.run(voice._reply('How many days left?', voice.VoiceRequest(speak=False)))
    assert result.action_success and '2 days' in result.response and not result.awaiting_reply
    assert topic[3] == []


def test_successfully_saved_date_can_seed_the_followup(topic):
    say('My exam was postponed')
    assert say('Robotics, November 3').success
    assert '2026-11-03' in say('When is it now?').message
    assert len(topic[3]) == 2  # Only the existing date generation and critic.


@pytest.mark.parametrize('question', ['When is it?', 'How many days left?', 'What was the previous date?'])
def test_no_topic_never_chooses_an_exam_by_recency(topic, question):
    result = say(question)
    assert result is not None and not result.success
    assert '2026-10-24' not in result.message and '2026-10-26' not in result.message
    assert topic[3] == []


def test_ambiguous_or_unknown_switch_clears_the_previous_topic(topic):
    say('When is my robotics exam?')
    result = say('When is my exam?')
    assert not result.success and 'name' in result.message.lower()
    assert not say('When is it?').success
    say('When is my robotics exam?')
    assert not say('What about my physics exam?').success
    assert not say('When is it?').success


@pytest.mark.parametrize('text', ['When is my first?', 'When is my latest?', 'What about the second one?'])
def test_unoffered_ordinals_do_not_select_a_saved_target(topic, text):
    from services.mind import commitment_topics
    parsed = commitment_topics.topics.match_turn(text)
    if parsed:
        assert not commitment_topics.topics.run(parsed).success
    assert not say('When is it?').success


@pytest.mark.parametrize('change', ['unrelated', 'cancel', 'forget', 'history', 'disabled', 'expiry', 'revision', 'row', 'deleted'])
def test_retired_changed_or_disabled_topics_cannot_answer(topic, monkeypatch, change):
    from services.mind import reference_context
    from services.mind.cognition import cognition
    from services.mind import conversation_context
    say('When is my robotics exam?')
    if change == 'unrelated':
        say('what is the date and time')
    elif change == 'cancel':
        result = say('never mind')
        assert result.success and 'topic' in result.message.lower()
        assert len(topic[2].history('robotics exam')) == 1
    elif change == 'forget':
        cognition.clear()
    elif change == 'history':
        conversation_context.clear()
    elif change == 'disabled':
        monkeypatch.setattr(config, 'COGNITION_ENABLED', False)
    elif change == 'expiry':
        after = reference_context.time.time() + reference_context.TTL_SECONDS + 1
        monkeypatch.setattr(reference_context.time, 'time', lambda: after)
    elif change == 'revision':
        revision(topic)
    else:
        with topic[2]._db() as db:
            if change == 'deleted':
                db.execute('DELETE FROM temporal_situations WHERE id=1')
            else:
                row = db.execute('SELECT body FROM temporal_situations WHERE id=1').fetchone()
                body = json.loads(row[0])
                body['noted'] = NOW.isoformat()
                db.execute('UPDATE temporal_situations SET body=? WHERE id=1', (json.dumps(body),))
    result = say('When is it?')
    assert not result.success and '2026-10-24' not in result.message


def test_stale_parsed_reference_cannot_read_the_newly_selected_topic(topic):
    from services.mind.commitment_topics import topics
    say('When is my robotics exam?')
    old = topics.match_turn('When is it?')
    say('When is my maths exam?')
    assert not topics.run(old).success


def test_telegram_cannot_read_switch_or_cancel_the_laptop_topic(topic):
    from services.automation.intent import remote_request
    from services.mind.commitment_topics import topics
    say('When is my robotics exam?')
    token = remote_request.set(True)
    try:
        for text in ('When is it?', 'What about my maths exam?', 'never mind'):
            assert topics.match_turn(text, remote=True) is None
            say(text)
    finally:
        remote_request.reset(token)
    assert 'robotics exam' in say('When is it?').message


def test_topic_survives_a_new_instance_and_pruned_original_episode(topic, monkeypatch):
    from services.mind import commitment_topics
    from services.mind.cognition import cognition
    say('When is my robotics exam?')
    with topic[1]._db() as db:
        db.execute('DELETE FROM owner_episodes')
    monkeypatch.setattr(commitment_topics, 'topics', commitment_topics.CommitmentTopics(cognition))
    assert '2026-10-24' in say('When is it?').message


@pytest.mark.parametrize('status', ['uncertain', 'completed', 'cancelled', 'postponed', 'range', 'past', 'today'])
def test_countdown_preserves_status_ranges_and_past_uncertainty(topic, status):
    with topic[2]._db() as db:
        body = json.loads(db.execute('SELECT body FROM temporal_situations WHERE id=1').fetchone()[0])
        body['status'] = status if status in {'uncertain', 'completed', 'cancelled', 'postponed'} else 'planned'
        if status == 'postponed':
            body['start'] = body['end'] = None
        elif status == 'range':
            body['end'] = '2026-10-25'
        elif status == 'past':
            body['start'] = body['end'] = '2026-10-21'
        elif status == 'today':
            body['start'] = body['end'] = '2026-10-22'
        db.execute('UPDATE temporal_situations SET body=? WHERE id=1', (json.dumps(body),))
    say('When is my robotics exam?')
    result = say('How many days left?')
    if status == 'today':
        assert result.success and 'today' in result.message.lower()
    elif status == 'past':
        assert 'ago' in result.message and 'completion' in result.message.lower()
    else:
        assert not result.success and 'days left' not in result.message.lower()


def test_previous_date_follows_its_direct_link_not_sorted_subject_history(topic):
    revision(topic)
    with topic[2]._db() as db:
        raw = db.execute('SELECT * FROM temporal_situations WHERE id=1').fetchone()
        body = json.loads(raw['body'])
        body['start'] = body['end'] = '2026-10-30'
        db.execute('INSERT INTO temporal_situations(body,source_key,subject_key,superseded_by) VALUES(?,?,?,?)',
                   (json.dumps(body), 'owner_episode:9999', raw['subject_key'], 3))
    say('When is my robotics exam?')
    result = say('What was the previous date?')
    assert result.success and '2026-10-24' in result.message and '2026-10-30' not in result.message


@pytest.mark.parametrize('mutation', ['missing', 'reverse', 'subject'])
def test_missing_or_mismatched_predecessor_is_unavailable(topic, mutation):
    revision(topic)
    say('When is my robotics exam?')
    with topic[2]._db() as db:
        if mutation == 'missing':
            db.execute('DELETE FROM temporal_situations WHERE id=1')
        elif mutation == 'reverse':
            db.execute('UPDATE temporal_situations SET superseded_by=2 WHERE id=1')
        else:
            body = json.loads(db.execute('SELECT body FROM temporal_situations WHERE id=1').fetchone()[0])
            body['subject'] = 'maths exam'
            db.execute('UPDATE temporal_situations SET body=? WHERE id=1', (json.dumps(body),))
    assert not say('What was the previous date?').success


def test_named_selection_checks_all_active_subjects_without_a_display_cutoff(topic):
    with topic[2]._db() as db:
        raw = db.execute('SELECT * FROM temporal_situations WHERE id=1').fetchone()
        for i in range(105):
            body = json.loads(raw['body'])
            body['subject'] = f'other {i} exam'
            db.execute('INSERT INTO temporal_situations(body,source_key,subject_key) VALUES(?,?,?)',
                       (json.dumps(body), f'owner_episode:{i+100}', body['subject']))
    assert say('When is my robotics exam?').success
    assert not say('When is my exam?').success


@pytest.mark.parametrize('text', ['open it', 'finish it', 'remind me then', 'move it to November 5'])
def test_topic_never_rewrites_action_pronouns(topic, text):
    from services.mind.commitment_topics import topics
    say('When is my robotics exam?')
    before = topic[2].history('robotics exam')
    assert topics.match_turn(text) is None
    assert topic[2].history('robotics exam') == before


def test_automation_early_route_retires_the_topic(topic, monkeypatch):
    from interfaces.api.routes import chat
    from services.browser.service import automation
    from services.automation.results import ActionResult
    async def handle(*args):
        return ActionResult(False, 'Synthetic automation result')
    monkeypatch.setattr(automation, 'handle', handle)
    say('When is my robotics exam?')
    asyncio.run(chat.chat(chat.ChatRequest(message='browse the web for robotics')))
    assert not say('When is it?').success


def test_topic_payload_and_replies_keep_private_text_out_of_relearning(topic):
    from services.mind.commitment_topics import topics, KIND
    from services.mind import reference_context
    before = topic[2].history('robotics exam')
    result = say('When is my robotics exam?')
    with topics.workspace._db() as db:
        saved = reference_context.read(db, KIND)
    assert set(saved['payload']) == {'target', 'version', 'epoch'}
    assert not result.repeatable and 'robotics' not in result.memory_message
    assert topic[2].history('robotics exam') == before and topic[3] == []


@pytest.mark.parametrize('failure', [OSError, sqlite3.OperationalError])
def test_optional_topic_storage_failure_cannot_deny_a_committed_date(topic, monkeypatch, failure):
    from services.mind.commitment_topics import CommitmentTopics
    def broken(*args):
        raise failure('Synthetic topic storage failure')
    monkeypatch.setattr(CommitmentTopics, 'remember', broken)
    say('My exam was postponed')
    result = say('Robotics, November 3')
    assert result.success and 'Saved' in result.message
    assert len(topic[2].history('robotics exam')) == 2
    assert not say('When is it?').success


def test_unreviewed_date_answer_cannot_seed_a_topic(topic, monkeypatch):
    say('When is my robotics exam?')
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
    say('My exam was postponed')
    assert not say('Robotics, November 3').success
    assert not say('When is it?').success
    result = say('When is my robotics exam?')
    assert result.success and 'Last saved report' in result.message and '2026-10-24' in result.message


def test_forgetting_removes_only_the_topic_reference_kind(topic):
    from services.mind.commitment_topics import topics, KIND
    from services.mind import reference_context
    from services.mind.cognition import cognition
    say('When is my robotics exam?')
    with topics.workspace._db() as db:
        reference_context.remember(db, 'task_followup', {'target': 22})
    cognition.clear()
    with topics.workspace._db() as db:
        assert reference_context.read(db, KIND) is None
        assert reference_context.read(db, 'task_followup')['payload']['target'] == 22


def test_epoch_change_fences_a_surviving_topic_row(topic):
    from services.mind.cognition import cognition
    from services.mind.executive import ExecutiveControl
    control = ExecutiveControl(cognition)
    control.status()
    say('When is my robotics exam?')
    with control._db() as db:
        db.execute('UPDATE executive_settings SET epoch=epoch+1 WHERE id=1')
    assert not say('When is it?').success


def test_pronoun_reads_do_not_extend_the_original_expiry(topic, monkeypatch):
    from services.mind import reference_context
    started = reference_context.time.time()
    say('When is my robotics exam?')
    monkeypatch.setattr(reference_context.time, 'time', lambda: started + 600)
    assert say('When is it?').success
    monkeypatch.setattr(reference_context.time, 'time', lambda: started + reference_context.TTL_SECONDS + 1)
    assert not say('When is it?').success


def test_remote_context_cannot_replay_a_parsed_laptop_reference_or_seed_one(topic):
    from services.automation.intent import remote_request
    from services.mind.commitment_topics import topics
    say('When is my robotics exam?')
    parsed = topics.match_turn('When is it?')
    maths = next(row for row in topic[2].evidence().values() if row['subject'] == 'maths exam')
    token = remote_request.set(True)
    try:
        assert topics.match_turn('When is it?') is None
        assert not topics.run(parsed).success
        topics.remember(maths)
    finally:
        remote_request.reset(token)
    assert 'robotics exam' in say('When is it?').message


def test_optional_topic_retirement_failure_cannot_block_date_clarification(topic, monkeypatch):
    from services.mind.commitment_topics import topics
    def broken(*args):
        raise sqlite3.OperationalError('Synthetic optional context failure')
    monkeypatch.setattr(topics, 'clear', broken)
    result = say('My exam was postponed')
    assert result.success and 'Which' in result.message
    assert say('Robotics, November 3').success
    assert len(topic[2].history('robotics exam')) == 2


def test_unavailable_topic_lookup_cannot_fall_through_to_search_or_models(topic, monkeypatch):
    from interfaces.api.routes import chat
    from services.mind.commitment_topics import topics
    say('When is my robotics exam?')
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError('Synthetic topic read failure')
    async def forbidden(*args, **kwargs):
        pytest.fail('An unavailable topic reached search or a model')
    monkeypatch.setattr(topics, 'match_turn', broken)
    monkeypatch.setattr(chat, 'build_file_context', forbidden)
    monkeypatch.setattr(chat, 'build_search_context', forbidden)
    monkeypatch.setattr('providers.failover.complete_with_failover', forbidden)
    result = asyncio.run(chat.chat(chat.ChatRequest(message='When is it?')))
    assert result.action_success is False and 'unavailable' in result.response.lower()


def test_remember_refuses_a_changed_or_superseded_target(topic):
    from services.mind.commitment_topics import topics
    old = next(row for row in topic[2].evidence().values() if row['subject'] == 'robotics exam')
    revision(topic)
    topics.remember(old)
    assert not say('When is it?').success
    current = next(row for row in topic[2].evidence().values() if row['subject'] == 'robotics exam')
    topics.remember({**current, 'subject': 'an invented subject'})
    assert not say('When is it?').success


def test_late_date_save_cannot_replace_a_newer_real_chat_topic(topic, monkeypatch):
    from interfaces.api.routes import chat
    from providers import failover
    original = failover.complete_with_failover
    async def complete(*args, **kwargs):
        result = await original(*args, **kwargs)
        if 'check_items' in json.loads(args[1][0].content):
            newer = await asyncio.create_task(chat.chat(chat.ChatRequest(message='When is my maths exam?')),
                                              context=contextvars.Context())
            assert newer.action_success
        return result
    monkeypatch.setattr(failover, 'complete_with_failover', complete)
    async def scenario():
        await chat.chat(chat.ChatRequest(message='My exam was postponed'))
        saved = await chat.chat(chat.ChatRequest(message='Robotics, November 3'))
        assert saved.action_success and '2026-11-03' in saved.response
        answer = await chat.chat(chat.ChatRequest(message='When is it?'))
        assert answer.action_success and 'maths exam' in answer.response
    asyncio.run(scenario())
    assert len(topic[2].history('robotics exam')) == 2


@pytest.mark.parametrize('operation', ['clear', 'named'])
def test_an_older_request_cannot_clear_or_bind_over_a_newer_topic(topic, operation):
    from services.mind.cognition import cognition, _turn
    from services.mind.commitment_topics import topics
    older = _turn.set('older-topic-query')
    try:
        cognition.record('request', 'chat', 'Synthetic older request')
        newer = _turn.set('newer-topic-query')
        try:
            cognition.record('request', 'voice', 'Synthetic newer request')
            assert say('When is my maths exam?').success
        finally:
            _turn.reset(newer)
        if operation == 'clear':
            topics.clear()
        else:
            assert not topics.run({'question': 'date', 'reference': 'robotics exam'}).success
    finally:
        _turn.reset(older)
    assert 'maths exam' in say('When is it?').message


def test_newer_telegram_request_does_not_block_local_saved_topic(topic):
    from services.mind.cognition import cognition, _turn
    from services.mind.commitment_topics import topics
    owner = _turn.set('local-save-request')
    try:
        cognition.record('request', 'chat', 'Synthetic local request')
        remote = _turn.set('remote-request')
        try:
            cognition.record('request', 'telegram', 'Synthetic remote request')
        finally:
            _turn.reset(remote)
        saved = next(row for row in topic[2].evidence().values() if row['subject'] == 'robotics exam')
        topics.remember(saved)
    finally:
        _turn.reset(owner)
    assert say('When is it?').success


def test_missing_request_record_cannot_seed_an_optional_topic(topic):
    from services.mind.cognition import _turn
    from services.mind.commitment_topics import topics
    owner = _turn.set('missing-or-pruned-local-request')
    try:
        saved = next(row for row in topic[2].evidence().values() if row['subject'] == 'robotics exam')
        topics.remember(saved)
    finally:
        _turn.reset(owner)
    assert not say('When is it?').success
