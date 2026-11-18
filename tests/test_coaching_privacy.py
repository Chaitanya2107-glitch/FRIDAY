import asyncio
from datetime import datetime, timedelta
import json

import pytest

from interfaces.api.routes import chat, voice
from services.mind import care, care_safeguard, coaching_commands, wording
from services.remote.context import conversation_only


async def forbidden(*args, **kwargs):
    pytest.fail('Private coaching reached a model, semantic learner or remote speech service')


@pytest.fixture
def local_only(monkeypatch):
    monkeypatch.setattr(chat, 'complete_with_failover', forbidden)
    monkeypatch.setattr(voice, 'complete_with_failover', forbidden)
    monkeypatch.setattr(chat.semantic_memory, 'learn_in_background', lambda *a, **k: pytest.fail('Private coaching entered semantic learning'))
    from services.mind.brain_memory import brain_memory
    monkeypatch.setattr(brain_memory, 'remember', lambda *a, **k: pytest.fail('Private coaching entered owner episodes'))


def test_chat_goal_setup_confirmation_and_unknown_reply_never_enter_history(local_only):
    first = asyncio.run(chat.chat(chat.ChatRequest(message='finish 100 PRIVATE_DSA_SENTINEL problems by Dec 15')))
    assert first.private and first.awaiting_reply and first.tokens_used == 0
    unknown = asyncio.run(chat.chat(chat.ChatRequest(message='my very private setup answer')))
    assert unknown.private and unknown.tokens_used == 0
    confirmed = asyncio.run(chat.chat(chat.ChatRequest(message='yes')))
    assert confirmed.private and 'saved privately' in confirmed.response
    assert not chat._memory.get_recent_history()


def test_sleep_setup_is_local_even_with_model_enabled_and_explicit_values(local_only, monkeypatch):
    from core.config import config
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', False)
    first = asyncio.run(chat.chat(chat.ChatRequest(message='set up sleep care bedtime 23:00 wake 07:00 from 21:00 to 23:30 cap 1')))
    assert first.private and first.awaiting_reply
    assert care.store().settings('sleep') is None
    saved = asyncio.run(chat.chat(chat.ChatRequest(message='yes')))
    assert saved.private and care.store().settings('sleep')['definition']['limit'] == '23:00'
    assert not chat._memory.get_recent_history()


@pytest.mark.parametrize('prefix', ['please ', 'Friday, could you please ', 'can you '])
def test_prefixed_private_goal_is_intercepted_before_history_or_provider(prefix, local_only, monkeypatch):
    from services.remote import conversation
    from services.mind.cognition import cognition
    monkeypatch.setattr(conversation, 'complete_with_failover', forbidden)
    message = prefix + 'track goal read 20 PRIVATE_PREFIX_SENTINEL pages daily'
    result = asyncio.run(chat.chat(chat.ChatRequest(message=message)))
    assert result.private and result.awaiting_reply and result.tokens_used == 0
    assert not chat._memory.get_recent_history()
    coaching_commands.cancel_pending()
    token = conversation_only.set(True)
    try:
        result = asyncio.run(chat.chat(chat.ChatRequest(message=message)))
        assert result.private and result.provider == 'local' and not coaching_commands.pending()
        direct = asyncio.run(conversation.answer(message))
        assert direct.provider == 'local'
    finally:
        conversation_only.reset(token)
    assert 'PRIVATE_PREFIX_SENTINEL' not in str(cognition.recent())


def test_remote_conversation_cannot_send_goal_setup_or_distress_to_models(local_only, monkeypatch):
    from services.remote import conversation
    monkeypatch.setattr(conversation, 'complete_with_failover', forbidden)
    token = conversation_only.set(True)
    try:
        result = asyncio.run(chat.chat(chat.ChatRequest(message='study 2 hours every weekday')))
        assert result.private and result.provider == 'local' and not result.allow_speech
        assert not coaching_commands.pending()
        result = asyncio.run(conversation.answer('finish 100 PRIVATE_REMOTE_SENTINEL problems by Dec 15'))
        assert result.provider == 'local'
        result = asyncio.run(chat.chat(chat.ChatRequest(message='I want to hurt myself')))
        assert result.response == care_safeguard.RESPONSE
        assert care_safeguard.active()
    finally:
        conversation_only.reset(token)


def test_disclosure_persists_only_pause_time_and_no_request_or_reply_text(local_only):
    from services.mind.cognition import cognition
    text = 'I cannot keep myself safe'
    result = asyncio.run(chat.chat(chat.ChatRequest(message=text)))
    assert result.private and result.response == care_safeguard.RESPONSE
    data = json.loads(care_safeguard.path().read_text())
    assert set(data) == {'paused_until'}
    with cognition._connect() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0
    assert not chat._memory.get_recent_history()


def test_voice_checkin_does_not_return_or_save_transcription(local_only):
    now = datetime.now()
    definition = dict(type='wellbeing', limit=1, window=['00:00', '23:59'], days=list(range(7)), cap=1,
                      categories=[], apps=[], context='any', voice=False)
    care.store().confirm(definition, now)
    result = asyncio.run(voice._reply('wellbeing 3', voice.VoiceRequest(speak=False)))
    assert result.private and result.transcription == '' and result.provider == 'local'
    assert not voice._memory.get_recent_history()


def test_phone_use_details_require_explicit_private_view_and_voice_is_off(local_only, monkeypatch):
    now = datetime.now()
    definition = dict(type='phone_use', limit=50, window=['00:00', '23:59'], days=list(range(7)), cap=1,
                      categories=['entertainment'], apps=[], context='any', voice=False)
    care.store().confirm(definition, now)
    care.store().claim(dict(type='phone_use', revision=1, key='private-view', text='PRIVATE_PHONE_DETAILS 50 minutes'), now)
    monkeypatch.setattr(chat, '_speak_in_background', lambda *a, **k: pytest.fail('Phone-use details were spoken without consent'))
    result = asyncio.run(chat.chat(chat.ChatRequest(message='show private care check', speak=True)))
    assert result.private and 'PRIVATE_PHONE_DETAILS' in result.response and not result.allow_speech
    assert not chat._memory.get_recent_history()


def test_wording_always_uses_plain_fallback_for_private_kinds(monkeypatch):
    from providers import failover
    monkeypatch.setattr(failover, 'complete_with_failover', forbidden)
    for kind in ('care', 'goal_coaching', 'coaching'):
        assert asyncio.run(wording.say(dict(kind=kind, answer='PRIVATE_FACTS'))) == 'PRIVATE_FACTS'


@pytest.mark.parametrize('message', ['care status', 'weekly care review', 'care experiments'])
def test_phone_use_voice_choice_also_covers_summaries(message, local_only, monkeypatch):
    from services.mind import care_review
    from tests.test_care import definition
    now = datetime.now()
    care.store().confirm(definition('phone_use'), now)
    care.store().confirm(definition('weekly_review'), now)
    monkeypatch.setattr(care_review, 'weekly', lambda *a: dict(text='PRIVATE_PHONE_REVIEW 50 minutes'))
    monkeypatch.setattr(chat, '_speak_in_background', lambda *a, **k: pytest.fail('Private phone summary was spoken without voice consent'))
    result = asyncio.run(chat.chat(chat.ChatRequest(message=message, speak=True)))
    assert result.private and not result.allow_speech
    monkeypatch.setattr(voice, '_speak_in_background', lambda *a, **k: pytest.fail('Private phone summary reached speech'))
    spoken = asyncio.run(voice._reply(message, voice.VoiceRequest(speak=True)))
    assert spoken.private and spoken.transcription == ''
