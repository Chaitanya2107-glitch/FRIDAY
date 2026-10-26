"""Ordinary chat questions retain their own source/version-checked provenance."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest

from core.config import config
from providers.base_provider import ProviderResponse
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import cognition
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate

NOW = datetime(2026, 10, 22, 15)


@pytest.fixture
def conversation(monkeypatch):
    from services.mind import dialogue, executive, cognition_context
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(dialogue, 'clock', lambda: NOW)
    monkeypatch.setattr(cognition_context, 'live_state', lambda: {'activity': 'idle', 'away': False})
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle', 'away': False,
                         'life_state': {'can_review': True, 'review_blocks': []}})
    episodes, temporal = BrainMemory(cognition), TemporalMemory(cognition)
    for subject, phrase in [('robotics exam', 'October 24'), ('maths exam', 'October 26')]:
        text = f'My {subject} is on {phrase}'
        ident = episodes.remember(text, now=NOW - timedelta(days=1))
        update = TemporalUpdate(source=f'owner_episode:{ident}', quote=text, subject=subject,
            status='planned', date_phrase=phrase, start=None, end=None, supersedes=[])
        known = episodes.evidence()
        with temporal._db() as db:
            temporal.save(db, temporal.resolve([update], known), NOW - timedelta(days=1), known)
    calls = []
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        calls.append(payload)
        if 'check_items' in payload:
            response = {'checks': [{'id': 0, 'supported': True, 'reason': 'The paired owner answer identifies this exact exam.'}]}
        else:
            pending = payload['pending_temporal_corrections']
            source, targets = next(iter(pending.items()))
            response = {'work_kind': 'situations', 'items': [{
                'source': source, 'quote': payload['evidence'][source]['text'],
                'subject': payload['evidence'][targets[0]]['subject'], 'status': 'planned',
                'date_phrase': '', 'supersedes': targets}]}
        return ProviderResponse(content=json.dumps(response), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    return dialogue.dialogue, episodes, temporal, calls


def say(text):
    from services.automation.intent import try_system_action
    return asyncio.run(try_system_action(text, 'openrouter'))


def test_ambiguous_report_then_named_date_saves_only_the_selected_commitment(conversation):
    dialogue, episodes, temporal, calls = conversation
    question = say('My exam was postponed')
    assert question and 'Which' in question.message and 'robotics exam' in question.message and 'maths exam' in question.message
    assert dialogue.awaiting() and calls == []
    answer = say('Robotics, November 3')
    assert answer.success and '2026-11-03' in answer.message
    assert not dialogue.awaiting() and len(calls) == 2
    history = temporal.history('robotics exam')
    assert len(history) == 2 and history[0]['start'] == '2026-11-03'
    assert history[0]['quote'] == 'Robotics, November 3' and history[0]['source_question'] == question.message
    assert history[1]['superseded_by'] == history[0]['id']
    assert len(temporal.history('maths exam')) == 1
    assert episodes.evidence()[history[0]['source']]['text'] == 'Robotics, November 3'


def test_name_only_selection_then_date_uses_the_issued_second_question(conversation):
    dialogue, _, temporal, _ = conversation
    say('My exam was postponed')
    question = say('Robotics')
    assert dialogue.awaiting() and 'date' in question.message.lower() and 'robotics exam' in question.message
    answer = say("It's on November 3.")
    assert answer.success and '2026-11-03' in answer.message
    saved = temporal.history('robotics exam')[0]
    assert saved['source_question'] == question.message and saved['quote'] == "It's on November 3."


@pytest.mark.parametrize('text', ['Robotics, maybe November 3', 'Robotics, November 3 or 4',
    'Robotics, not November 3', 'Robotics, 2026-02-30', 'Robotics, next Friday',
    'Robotics, Thursday', 'Chemistry, November 3', 'November 3', 'Robotics, November 3?'])
def test_ambiguous_uncertain_or_unoffered_answer_cannot_change_dates(conversation, text):
    _, _, temporal, calls = conversation
    say('My exam was postponed')
    result = say(text)
    assert result is not None and len(temporal.history('robotics exam')) == 1
    assert len(temporal.history('maths exam')) == 1 and calls == []


def test_local_chat_question_can_receive_a_voice_answer_without_search_or_learning(conversation, monkeypatch):
    from interfaces.api.routes import chat, voice
    async def forbidden(*args, **kwargs):
        pytest.fail('A clarification reached search or normal conversation')
    monkeypatch.setattr(chat, 'build_file_context', forbidden)
    monkeypatch.setattr(voice, 'build_file_context', forbidden)
    monkeypatch.setattr(chat.humour, 'hear', lambda *a: pytest.fail('Clarification reached humour learning'))
    monkeypatch.setattr(chat.talk, 'hear', lambda *a: pytest.fail('Clarification consumed a proactive question'))
    question = asyncio.run(chat.chat(chat.ChatRequest(message='My exam was postponed')))
    assert question.awaiting_reply
    answer = asyncio.run(voice._reply('Robotics, November 3', voice.VoiceRequest(speak=False)))
    assert answer.action_success and not answer.awaiting_reply and '2026-11-03' in answer.response


def test_remote_reply_cannot_consume_the_laptop_question(conversation):
    from services.automation.intent import remote_request
    dialogue, _, temporal, _ = conversation
    say('My exam was postponed')
    token = remote_request.set(True)
    try:
        result = say('Robotics, November 3')
        assert result is None or not result.success
    finally:
        remote_request.reset(token)
    assert dialogue.awaiting() and len(temporal.history('robotics exam')) == 1
    assert say('Robotics, November 3').success


@pytest.mark.parametrize('change', ['forget', 'target', 'expiry', 'unrelated', 'cancel'])
def test_changed_or_retired_questions_cannot_revive_a_revision(conversation, monkeypatch, change):
    from services.mind import dialogue as module
    dialogue, _, temporal, calls = conversation
    say('My exam was postponed')
    if change == 'forget':
        cognition.clear()
    elif change == 'target':
        with temporal._db() as db:
            body = json.loads(db.execute('SELECT body FROM temporal_situations WHERE id=1').fetchone()[0])
            body['noted'] = '2026-10-22T12:00:00'
            db.execute('UPDATE temporal_situations SET body=? WHERE id=1', (json.dumps(body),))
    elif change == 'expiry':
        monkeypatch.setattr(module, 'clock', lambda: NOW + timedelta(hours=1))
    elif change == 'unrelated':
        say('what is the date and time')
    else:
        assert say('never mind') is not None
    result = say('Robotics, November 3')
    assert result is None or '2026-11-03' not in result.message
    assert len(temporal.history('robotics exam')) == (0 if change == 'forget' else 1)
    assert calls == []


def test_independent_rejection_never_confirms_an_update(conversation, monkeypatch):
    _, _, temporal, _ = conversation
    from services.mind import reasoning
    async def reject(*args, **kwargs):
        raise reasoning.UnsupportedConclusion('Synthetic independent rejection')
    monkeypatch.setattr(reasoning, 'critique', reject)
    say('My exam was postponed')
    result = say('Robotics, November 3')
    assert not result.success and 'not updated' in result.message.lower()
    assert len(temporal.history('robotics exam')) == 1


def test_silence_is_not_a_saved_revision(conversation, monkeypatch):
    async def silence(*args, **kwargs):
        return ProviderResponse(content='{"work_kind":"silence"}', provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', silence)
    say('My exam was postponed')
    result = say('Robotics, November 3')
    assert not result.success and 'not updated' in result.message.lower()
    assert len(conversation[2].history('robotics exam')) == 1


def test_deferred_answer_stays_source_linked_and_status_requires_real_persistence(conversation, monkeypatch):
    dialogue, episodes, temporal, calls = conversation
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
    say('My exam was postponed')
    result = say('Robotics, November 3')
    assert not result.success and 'not updated' in result.message.lower() and calls == []
    pending = temporal.pending_corrections({**temporal.evidence(), **episodes.evidence()})
    assert list(pending.values()) == [['temporal:1']]
    assert 'not updated' in say('follow-up status').message.lower()
    assert len(temporal.history('robotics exam')) == 1


def test_restarted_handler_retains_the_offered_question(conversation, monkeypatch):
    from services.mind import dialogue as module
    say('My exam was postponed')
    monkeypatch.setattr(module, 'dialogue', module.Dialogue(cognition))
    assert say('Robotics, November 3').success


def test_relative_date_anchors_to_answer_receipt_not_question_or_review(conversation, monkeypatch):
    from services.mind import dialogue as module
    _, _, temporal, _ = conversation
    say('My robotics exam was postponed')
    monkeypatch.setattr(module, 'clock', lambda: NOW + timedelta(minutes=10))
    assert say('tomorrow').success
    assert temporal.history('robotics exam')[0]['start'] == '2026-10-23'


def test_a_new_unmatched_report_retires_the_older_question(conversation):
    dialogue, _, temporal, _ = conversation
    say('My robotics exam was postponed')
    assert dialogue.awaiting()
    assert not say('My chemistry exam was postponed').success
    assert not dialogue.awaiting()
    result = say('November 3')
    assert result is None or not result.success
    assert len(temporal.history('robotics exam')) == 1


def test_unresolved_report_and_name_selection_are_withheld_from_recall(conversation):
    _, episodes, _, _ = conversation
    say('My exam was postponed')
    say('Robotics')
    with episodes._db() as db:
        rows = db.execute("SELECT recall_withheld FROM owner_episodes WHERE text IN ('My exam was postponed', 'Robotics')").fetchall()
    assert len(rows) == 2 and all(row[0] for row in rows)
    recalled = episodes.recall('exam postponed robotics', limit=8)
    assert all(row['text'] not in {'My exam was postponed', 'Robotics'} for row in recalled)


@pytest.mark.parametrize('change', ['target', 'origin', 'question', 'answer', 'epoch', 'forget', 'disabled', 'lease'])
def test_changes_during_inference_cannot_commit_or_confirm(conversation, monkeypatch, change):
    from services.mind import reasoning
    _, _, temporal, _ = conversation
    real = reasoning.critique
    async def change_after_critique(*args, **kwargs):
        await real(*args, **kwargs)
        with cognition._lock, cognition._connect() as db:
            if change == 'target':
                body = json.loads(db.execute('SELECT body FROM temporal_situations WHERE id=1').fetchone()[0])
                body['noted'] = '2026-10-22T12:00:00'
                db.execute('UPDATE temporal_situations SET body=? WHERE id=1', (json.dumps(body),))
            elif change == 'origin':
                db.execute("UPDATE owner_episodes SET text='My maths exam was postponed' WHERE text='My exam was postponed'")
            elif change == 'question':
                row = db.execute("SELECT * FROM dialogue_clarifications WHERE state='answered'").fetchone()
                payload = json.loads(row['payload'])
                payload['question'] = 'When is the maths exam?'
                db.execute('UPDATE dialogue_clarifications SET payload=? WHERE id=?', (json.dumps(payload), row['id']))
            elif change == 'answer':
                db.execute("UPDATE owner_episodes SET text='Maths, December 4' WHERE text='Robotics, November 3'")
            elif change == 'epoch':
                db.execute('UPDATE executive_settings SET epoch=epoch+1')
            elif change == 'lease':
                db.execute("UPDATE executive_reviews SET expires=0 WHERE state='running'")
        if change == 'forget':
            cognition.clear()
        if change == 'disabled':
            monkeypatch.setattr(config, 'COGNITION_ENABLED', False)
    monkeypatch.setattr(reasoning, 'critique', change_after_critique)
    say('My exam was postponed')
    result = say('Robotics, November 3')
    assert not result.success and 'not updated' in result.message.lower()
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    assert len(temporal.history('robotics exam')) == (0 if change == 'forget' else 1)


def test_source_link_cannot_be_bypassed_after_a_target_change(conversation, monkeypatch):
    _, episodes, temporal, _ = conversation
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
    say('My exam was postponed')
    say('robotics exam, November 3')
    with temporal._db() as db:
        body = json.loads(db.execute('SELECT body FROM temporal_situations WHERE id=1').fetchone()[0])
        body['noted'] = '2026-10-22T12:00:00'
        db.execute('UPDATE temporal_situations SET body=? WHERE id=1', (json.dumps(body),))
    known = {**temporal.evidence(), **episodes.evidence()}
    answer = next(row for row in known.values() if row.get('text') == 'robotics exam, November 3')
    assert answer['date_clarification']['invalid']
    value = TemporalUpdate(source=answer['id'], quote=answer['text'], subject='robotics exam', status='planned',
                           date_phrase='November 3', start=None, end=None, supersedes=['temporal:1'])
    with pytest.raises(ValueError):
        temporal.validate(temporal.resolve([value], known), known)
    with pytest.raises(ValueError):
        temporal.validate([value.model_copy(update={'subject': 'new exam', 'supersedes': []})], known)


def test_storage_failure_never_produces_a_saved_acknowledgement(conversation, monkeypatch):
    import sqlite3
    from services.mind.reasoning_store import ReasoningStore
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('Synthetic storage failure')
    monkeypatch.setattr(ReasoningStore, 'save', fail)
    say('My exam was postponed')
    result = say('Robotics, November 3')
    assert not result.success and 'not updated' in result.message.lower()
    assert len(conversation[2].history('robotics exam')) == 1


def test_deferred_answer_can_use_the_existing_background_review(conversation, monkeypatch):
    from services.mind.executive import ExecutiveControl
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
    say('My exam was postponed')
    assert not say('Robotics, November 3').success
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    result = asyncio.run(ExecutiveControl(cognition).review(NOW + timedelta(minutes=1)))
    assert result['status'] == 'completed'
    assert say('follow-up status').success
    assert conversation[2].history('robotics exam')[0]['start'] == '2026-11-03'


def test_requested_review_keeps_existing_spacing_and_hourly_budget(conversation):
    from services.mind.executive import ExecutiveControl
    _, _, temporal, calls = conversation
    say('My robotics exam was postponed')
    assert say('November 3').success and len(calls) == 2
    say('My maths exam was postponed')
    second = say('November 4')
    assert not second.success and len(calls) == 2
    assert len(temporal.history('maths exam')) == 1
    assert ExecutiveControl(cognition).status()['reviews_this_hour'] == 1


@pytest.mark.parametrize('block', ['gaming', 'typing', 'call', 'speaking', 'listening', 'pending_reply', 'state_unavailable'])
def test_attention_gates_defer_without_a_model_call(conversation, monkeypatch, block):
    from services.mind import executive
    monkeypatch.setattr(executive, 'attention_state', lambda: {
        'life_state': {'can_review': False, 'review_blocks': [block]}})
    say('My exam was postponed')
    result = say('Robotics, November 3')
    assert not result.success and conversation[3] == []
    assert len(conversation[2].history('robotics exam')) == 1


def test_foreground_review_does_not_replace_a_running_background_lease(conversation):
    from services.mind.executive import ExecutiveControl
    control = ExecutiveControl(cognition)
    now = datetime.now()
    situation = control.capture(now, known=conversation[2].evidence(), attention={})
    control.enqueue(situation, now)
    job = control.claim(now)
    say('My exam was postponed')
    assert not say('Robotics, November 3').success
    with control._db() as db:
        assert control._valid(db, job, now.timestamp())
    assert conversation[3] == []


def test_conversation_answer_does_not_execute_embedded_commands(conversation, monkeypatch):
    from services.automation import intent
    monkeypatch.setattr(intent, '_run_action', lambda *a, **kw: pytest.fail('A dialogue answer executed a command'))
    say('My exam was postponed')
    result = say('Robotics, November 3; open calculator')
    assert not result.success and conversation[3] == []
    assert len(conversation[2].history('robotics exam')) == 1


@pytest.mark.parametrize('text', ["It's raining today", 'That movie was great', 'Maybe I should sleep',
                                'Next semester will be easier'])
@pytest.mark.parametrize('expired', [False, True])
def test_unrelated_chat_retires_the_question_and_reaches_normal_routing(conversation, monkeypatch, text, expired):
    from services.mind import dialogue as module
    say('My exam was postponed')
    if expired:
        monkeypatch.setattr(module, 'clock', lambda: NOW + timedelta(hours=1))
    assert module.dialogue.match_turn(text) is None
    assert not module.dialogue.awaiting()
    assert conversation[3] == []


@pytest.mark.parametrize('text', ['Robotics November 3', 'Robotics exam November 3', 'the first one tomorrow'])
def test_voice_names_need_no_punctuation(conversation, monkeypatch, text):
    from interfaces.api.routes import chat, voice
    async def forbidden(*args, **kwargs):
        pytest.fail('A punctuation-free date answer escaped into normal chat or search')
    monkeypatch.setattr(voice, 'build_file_context', forbidden)
    question = asyncio.run(chat.chat(chat.ChatRequest(message='My exam was postponed')))
    assert question.awaiting_reply
    answer = asyncio.run(voice._reply(text, voice.VoiceRequest(speak=False)))
    assert answer.action_success and not answer.awaiting_reply
    expected = '2026-10-23' if 'tomorrow' in text else '2026-11-03'
    # The first offered item is maths, because current commitments are newest first.
    subject = 'maths exam' if 'first' in text else 'robotics exam'
    assert conversation[2].history(subject)[0]['start'] == expected


def test_cancel_during_generation_fences_the_late_result(conversation, monkeypatch):
    from services.automation import intent
    from providers import failover
    original = failover.complete_with_failover
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def pause(*args, **kwargs):
            if 'pending_temporal_corrections' in json.loads(args[1][0].content):
                started.set()
                await release.wait()
            return await original(*args, **kwargs)
        monkeypatch.setattr(failover, 'complete_with_failover', pause)
        await intent.try_system_action('My exam was postponed', 'openrouter')
        active = asyncio.create_task(intent.try_system_action('Robotics, November 3', 'openrouter'))
        await asyncio.wait_for(started.wait(), 5)
        cancelled = await intent.try_system_action('never mind', 'openrouter')
        assert cancelled.success and 'cancelled' in cancelled.message
        release.set()
        assert not (await asyncio.wait_for(active, 5)).success
    asyncio.run(scenario())
    assert len(conversation[2].history('robotics exam')) == 1


def test_new_postponement_retires_an_older_queued_answer(conversation, monkeypatch):
    from services.mind import executive
    _, episodes, temporal, calls = conversation
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
    say('My robotics exam was postponed')
    say('November 3')
    assert temporal.pending_corrections({**temporal.evidence(), **episodes.evidence()})
    say('My robotics exam was postponed')
    assert not temporal.pending_corrections({**temporal.evidence(), **episodes.evidence()})
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    # Even if a later idle review runs, the retired answer cannot revise the date.
    asyncio.run(executive.ExecutiveControl(cognition).review(NOW + timedelta(minutes=1)))
    assert len(temporal.history('robotics exam')) == 1
    assert not say('follow-up status').success


def test_scoped_claim_does_not_take_another_situation_or_spend_budget(conversation):
    from services.mind.executive import ExecutiveControl
    control = ExecutiveControl(cognition)
    now = datetime.now()
    situation = control.capture(now, known=conversation[2].evidence(), attention={})
    control.enqueue(situation, now)
    assert control.claim(now, signature='a different situation') is None
    assert control.status(now)['reviews_this_hour'] == 0
    assert control.claim(now, signature=situation['signature'])


def test_requested_question_retires_a_proactive_offer_without_learning_an_answer(conversation, monkeypatch):
    from services.mind import talk
    talk._save({**talk.load(), 'pending': {'where': 'asked', 'at': datetime.now().timestamp(),
        'question': 'What did you eat?', 'offered': True}})
    monkeypatch.setattr(talk, '_learn_answer', lambda *a: pytest.fail('A date answer trained the unrelated question'))
    say('My exam was postponed')
    assert not talk.load().get('pending')
    assert say('Robotics, November 3').success
