import asyncio
from datetime import datetime

import numpy as np
import pytest

from services.files import embed
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition


@pytest.mark.parametrize('semantic', [False, True])
def test_unsupported_query_term_cannot_be_overruled_by_shared_description(tmp_path, monkeypatch, semantic):
    memory = BrainMemory(Cognition(tmp_path / 'identity.db'))
    memory.remember('The bicycle rear tyre loses air overnight.')
    monkeypatch.setattr(embed, 'encode_local', lambda *a, **kw: np.array([[1., 0.], [1., 0.]]))
    if semantic:
        assert asyncio.run(memory.recall_checked('motorcycle rear tyre loses air')) == []
    else:
        assert memory.recall('motorcycle rear tyre loses air') == []
    assert memory.recall('bicycle rear tyre')


def test_partial_paraphrase_abstains_but_full_rewording_can_still_retrieve(tmp_path, monkeypatch):
    memory = BrainMemory(Cognition(tmp_path / 'identity.db'))
    memory.remember('The hiking rucksack has a damaged clasp.')
    monkeypatch.setattr(embed, 'encode_local', lambda *a, **kw: np.array([[1., 0.], [1., 0.]]))
    async def compatible(query, *args, **kwargs):
        return query.startswith('backpack')
    monkeypatch.setattr('services.mind.recall_review.supports', compatible)
    assert memory.recall('suitcase damaged clasp') == []
    assert asyncio.run(memory.recall_checked('backpack fastening broken'))


def test_receipt_timestamp_is_not_a_date_phrase_but_unique_quoted_date_can_be_recovered():
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    quote = 'My geometry test is tomorrow'
    known = {'owner_episode:1': {'kind': 'owner_message', 'channel': 'chat', 'text': quote,
                                'noted': datetime(2026, 10, 21, 12).isoformat()}}
    value = TemporalUpdate(source='owner_episode:1', quote=quote, subject='geometry test',
        status='planned', date_phrase=known['owner_episode:1']['noted'], start=None, end=None, supersedes=[])
    result = TemporalMemory.resolve([value], known)[0]
    TemporalMemory.validate([result], known)
    assert result.date_phrase == 'tomorrow' and result.start == result.end == '2026-10-22'


@pytest.mark.parametrize('quote,status,supersedes', [
    ('My geometry test is tomorrow or Friday', 'planned', []),
    ('My geometry test is not tomorrow', 'planned', []),
    ('My geometry test was postponed from tomorrow', 'postponed', []),
    ('My geometry test was postponed from tomorrow', 'planned', ['temporal:1']),
])
def test_invalid_date_field_is_not_repaired_from_ambiguous_or_corrected_quote(quote, status, supersedes):
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    known = {'owner_episode:1': {'kind': 'owner_message', 'channel': 'chat', 'text': quote,
                                'noted': '2026-10-21T12:00:00'}}
    value = TemporalUpdate(source='owner_episode:1', quote=quote, subject='geometry test',
        status=status, date_phrase=known['owner_episode:1']['noted'], start=None, end=None, supersedes=supersedes)
    result = TemporalMemory.resolve([value], known)[0]
    assert result.date_phrase == value.date_phrase and result.start is None
    with pytest.raises(ValueError):
        TemporalMemory.validate([result], known)


@pytest.mark.parametrize('phrase', ['to Saturday', 'on Saturday', 'for Saturday'])
def test_dated_postponement_keeps_its_new_date_in_shared_views(tmp_path, phrase):
    from services.mind.life_state import LifeState
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    now = datetime(2026, 10, 21, 12)
    store = Cognition(tmp_path / 'dated-change.db')
    memory, temporal = BrainMemory(store), TemporalMemory(store)
    text = f'My geometry assessment was postponed {phrase}'
    ident = memory.remember(text, now=now)
    item = TemporalUpdate(source=f'owner_episode:{ident}', quote=text, subject='geometry assessment',
        status='postponed', date_phrase=phrase, start=None, end=None, supersedes=[])
    resolved = TemporalMemory.resolve([item], memory.evidence())[0]
    assert resolved.start == resolved.end == '2026-10-24'
    with temporal._db() as db:
        temporal.save(db, [resolved], now, memory.evidence())
    view = temporal.snapshot(now)
    assert not view['unresolved'] and view['upcoming'][0]['start'] == '2026-10-24'
    behavior = LifeState(store).assess(now, temporal.evidence(), {'activity': 'idle'}, {'on': True})
    assert behavior['responsibilities']['upcoming'] and not behavior['responsibilities']['unresolved']


@pytest.mark.parametrize('phrase', ['to next Saturday', 'from tomorrow', 'after Saturday', 'to Saturday or Sunday'])
def test_calendar_prefix_does_not_turn_ambiguous_or_old_dates_into_new_dates(phrase):
    from services.mind.temporal_memory import anchored_dates
    assert anchored_dates(phrase, datetime(2026, 10, 21, 12)) is None
