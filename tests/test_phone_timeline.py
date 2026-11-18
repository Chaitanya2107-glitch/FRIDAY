from datetime import datetime, timedelta
from types import SimpleNamespace
import asyncio
import pytest

from services.activity import timeline, attention, phone_commands
from services.phone_signals.store import PhoneStore
from services.mind import phone_patterns, thoughts, knowledge, wording, talk


@pytest.fixture
def day(tmp_path, monkeypatch):
    now = datetime(2026, 11, 14, 12)
    path = tmp_path / 'phone.db'
    monkeypatch.setattr(timeline, 'DEFAULT_PATH', path)
    store = PhoneStore(path, clock=now.timestamp)
    def event(kind, payload, minutes=0, handset='a'):
        return dict(id=f'event_{kind}_{minutes}_0123456789', timestamp=(now-timedelta(minutes=minutes)).timestamp(), type=kind, payload=payload)
    app = event('app_usage', dict(package='com.instagram.android', label='Instagram', category=4,
                start=(now-timedelta(minutes=20)).timestamp(), end=now.timestamp()))
    store.ingest('a', [app, event('screen', dict(state='unlocked', unlock_count=1)), event('motion', dict(activity='walking'))], 0)
    log = SimpleNamespace(moves=lambda *args: [(now.replace(hour=10).isoformat(), 'editor', 'PRIVATE TITLE', 3600, 'coding', None)])
    return now, path, store, log


def test_merge_clip_overlap_and_totals(day):
    now, path, _, log = day
    rows = timeline.segments(now.replace(hour=0), now, log=log, path=path)
    assert {r['device'] for r in rows} == {'laptop', 'phone'}
    assert 'PRIVATE TITLE' not in str(rows)
    assert timeline.totals(rows) == dict(laptop=3600, phone=1200)
    assert timeline.normalize([dict(device='phone', app='a', category='other', start=0, end=20),dict(device='phone', app='b', category='other', start=10, end=30)])[0]['end'] == 10


def test_attention_and_flap(day, monkeypatch):
    now, path, *_ = day
    events = timeline.phone_events(0, now.timestamp(), path=path)
    assert attention.resolve(events, now, 400)['attention'] == 'phone'
    assert attention.resolve(events, now, 1)['attention'] == 'both'
    assert attention.resolve([], now, 1)['attention'] == 'laptop'
    assert attention.resolve([], now, 400)['attention'] == 'away'
    monkeypatch.setattr(attention, '_stable', 'laptop'); monkeypatch.setattr(attention, '_candidate', None)
    for seconds in (0, 10, 20):
        assert attention.where_is_attention(now+timedelta(seconds=seconds), events=events, laptop_idle=400)['attention'] == 'laptop'
    assert attention.where_is_attention(now+timedelta(seconds=31), events=events, laptop_idle=400)['attention'] == 'phone'


def test_thought_owner_reason_repeat_and_forget(day):
    now, path, store, log = day
    rows = timeline.segments(now-timedelta(days=1), now, log=log, path=path)
    events = timeline.phone_events(0, now.timestamp(), path=path)
    findings = phone_patterns.findings(rows, events, now, 'study')
    assert findings[0][1] == 'distraction'
    tid = thoughts.add('phone_pattern', 'phone:a:distraction', dict(pattern='phone:a:distraction', device='a', finding='distraction', confirmed=False), .7, now)
    assert thoughts.add('phone_pattern', 'phone:a:distraction', {}, .7, now) is None
    thoughts.answered(tid, 'I was taking a break, not distracted', now)
    assert 'break' in thoughts.reason_for('phone:a:distraction')
    phone_patterns.forget('a')
    assert thoughts.get(tid) is None and thoughts.reason_for('phone:a:distraction') is None


def test_no_model_wording_and_unknown_flow(day, monkeypatch):
    now, *_ = day
    from providers import failover
    async def forbidden(*args, **kwargs):
        raise AssertionError('Phone data reached model')
    monkeypatch.setattr(failover, 'complete_with_failover', forbidden)
    raw = dict(kind='phone_pattern', finding='sleep', seconds=3600)
    assert 'possible' in asyncio.run(wording.say(raw))
    phone_patterns.observe_android('org.secret.app', 'Secret', 'other', 120, now, 'a')
    thing = knowledge.get('app:phone:a:org.secret.app')
    assert thing and thing.source == 'rule'
    assert asyncio.run(knowledge.look_up(thing, now)) is None
    assert all(not t.name.startswith('phone:') for t in knowledge.regulars(0))
    knowledge.teach(thing.key, 'This is a college study app')
    assert knowledge.get(thing.key).source == 'boss'


@pytest.mark.parametrize('query', ['what am I using on my phone', 'how long was I on Instagram today', 'which device have I used more today', 'when did I last use my phone', 'what did I do after class'])
def test_matchers_are_anchored(query):
    assert phone_commands.match_command(query)
    assert not phone_commands.match_command('search the web for '+query)


def test_sleep_estimate_is_not_fact():
    now = datetime(2026,11,14,6)
    events = [dict(device='a',timestamp=now.timestamp(),type='screen',payload=dict(state='off')),dict(device='a',timestamp=now.timestamp(),type='battery',payload=dict(charging=True))]
    result = attention.resolve(events, now, 999)
    assert result['sleep_estimate'] and 'not proof' in result['reason']


def test_evening_answer_stays_local(day, monkeypatch):
    now, *_ = day
    from services.mind import brain_memory
    from services.memory.semantic import semantic_memory
    def forbidden(*a, **kw):
        raise AssertionError('Phone answer entered generic memory')
    monkeypatch.setattr(brain_memory.brain_memory, 'remember', forbidden)
    monkeypatch.setattr(semantic_memory, 'learn_in_background', forbidden)
    monkeypatch.setattr('services.automation.intent._match_local_step', lambda *_: None)
    tid = thoughts.add('phone_pattern', 'phone:a:sleep', dict(pattern='phone:a:sleep', finding='sleep', device='a'), .7, now)
    line = asyncio.run(talk.compose(None, 'day_review', {}, now))
    assert line['thought'] == tid and line['phone_private']
    talk._record(line, 'evening', now.timestamp())
    assert talk.hear('I was awake reading', now.timestamp()+1) == 'answered'
    assert thoughts.reason_for('phone:a:sleep') == 'I was awake reading'


def test_known_sleep_and_place_frequency():
    now = datetime(2026,11,14,8)
    def e(kind, time, payload):
        return dict(device='a', type=kind, timestamp=time.timestamp(), payload=payload)
    off = now-timedelta(hours=10)
    events = [e('screen',off,dict(state='off')),e('battery',off,dict(charging=True)), e('screen',now-timedelta(hours=1),dict(state='unlocked')),
              e('sleep',now,dict(date=now.date().isoformat(),minutes=510))]
    for n in range(3):
        at = now-timedelta(days=n, hours=1)
        events += [e('places',at,dict(place='home',transition='left')),e('places',at+timedelta(minutes=30),dict(place='college',transition='entered'))]
    found = phone_patterns.findings([], sorted(events,key=lambda r:r['timestamp']), now, 'chill')
    assert {'sleep','place_routine'} <= {f[1] for f in found}
    sleep = next(f[2] for f in found if f[1]=='sleep')
    assert sleep['seconds'] == 9*3600 and sleep['health_minutes'] == 510


def test_forget_rebuilds_category_cache(day):
    from services.activity import categories
    now, *_ = day
    phone_patterns.observe_android('org.unknown', 'Unknown', 'other', 120, now, 'a')
    knowledge.teach('app:phone:a:org.unknown', 'A study tool')
    assert 'phone:a:org.unknown' in categories.LEARNED['app']
    phone_patterns.forget('a')
    assert 'phone:a:org.unknown' not in categories.LEARNED['app']


def test_voice_queries_are_private_and_offline(day, monkeypatch):
    from interfaces.api.routes import voice
    from providers import failover
    async def forbidden(*a, **k):
        raise AssertionError('Voice phone query reached a model')
    monkeypatch.setattr(failover, 'complete_with_failover', forbidden)
    response = asyncio.run(voice._reply('which device have I used more today', voice.VoiceRequest(speak=False)))
    assert response.private and 'Recorded today' in response.response
