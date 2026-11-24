"""Life graph behavior over owner fixtures, including public local entry points."""

import asyncio
from datetime import datetime
import json
import re
import sqlite3
from types import SimpleNamespace

import pytest

from core.config import config
from services.activity import projects
from services.automation import command_slots, intent, whatsapp
from services.college import store as college_store
from services.memory import notes
from services.mind import evening, goals, goals_sources, graph_commands, graph_sources, knowledge
from services.mind.graph import Node, graph
from services.presence import anticipation, triage
from services.proactive import deadlines, timetable
from services.settings_store import save


NOW = datetime(2026, 11, 23, 8)
PHYSICS = dict(id='physics-lab', what='Physics Lab Record', subject='Physics', kind='assignment',
               due='2026-11-24T17:00', done=False)
DSA = dict(id='dsa-lab', what='DSA Lab Record', subject='DSA', kind='assignment',
           due='2026-11-25T18:00', done=False)
EXAM = dict(id='physics-exam', what='Physics Midterm Exam', subject='Physics', kind='exam',
            due='2026-11-26T09:00', venue='Lab 7', done=False)
SLOTS = [dict(day='monday', subject='Physics', start='09:00', end='10:00', room='A-12'),
         dict(day='tuesday', subject='DSA', start='10:00', end='11:00', room='B-4')]
SUBJECTS = {'physics': dict(subject='Physics', faculty='Prof Elena Rao', room='A-12', email='fixture@example.test'),
            'dsa': dict(subject='Data Structures and Algorithms', faculty='Dr Maya Sen', room='B-4')}


def ask(text):
    reply = asyncio.run(graph_commands.try_command(text, now=NOW))
    assert reply is not None, text
    return reply


def stage(text):
    reply = ask(text)
    assert reply.success
    match = re.search(r'#(\d+)', reply.message)
    assert match, reply.message
    return int(match[1])


def approve(text):
    assert ask(f'confirm graph link {stage(text)}').success


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'FRIDAY_LLM', 'off')
    save(timetable.path, SLOTS)
    save(college_store.path('subjects.json'), SUBJECTS)
    save(deadlines.path, [PHYSICS, DSA, EXAM])
    folder = tmp_path / 'optics'
    folder.mkdir()
    save(projects.path, {'optics lab': {'path': str(folder)}, 'queue visualizer': {'path': str(tmp_path)}})
    phone = config.MEMORY_DIR / 'phone' / 'phone_events.db'
    phone.parent.mkdir(parents=True)
    with sqlite3.connect(phone) as db:
        db.execute('CREATE TABLE phone_events (type TEXT, payload TEXT)')
        db.executemany('INSERT INTO phone_events VALUES(?,?)', [
            ('places', json.dumps(dict(place='North Library', transition='entered'))),
            ('places', json.dumps(dict(place='North Library', transition='left'))),
            ('places', json.dumps(dict(place='Reject Me', transition='entered', latitude=0))),
            ('notifications', 'SYNTHETIC_INVALID_NOTIFICATION_PAYLOAD'),
            ('contacts', 'SYNTHETIC_INVALID_CONTACT_PAYLOAD'),
            ('messages', 'SYNTHETIC_INVALID_MESSAGE_PAYLOAD')])
    return graph, folder


def test_confirmed_sources_and_live_revision(dataset):
    thing = knowledge.requested_thing('Obsidian', 'app', NOW)
    knowledge.teach(thing.key, 'Personal notes app.', NOW)
    knowledge.requested_thing('Unverified App', 'app', NOW)
    definition = dict(title='Physics practice', target=10, unit='problems', deadline='2026-12-01',
                      cadence=None, source={'kind': 'manual'}, review_window=dict(day=6, start='18:00', end='21:00'))
    goals_sources.save(goals._memory(), definition, 'A personal goal.', now=NOW)
    view = graph_sources.refresh()
    assert graph.path == config.MEMORY_DIR / 'life_graph.db'
    for name, kind in [('Physics', 'course'), ('Lab 7', 'place'), ('Physics Midterm Exam', 'exam'),
                       ('North Library', 'place'), ('Optics Lab', 'project'), ('Physics practice', 'goal'),
                       ('Obsidian', 'app')]:
        assert [n['kind'] for n in view.resolve(name, fuzzy=False)] == [kind]
    assert not view.resolve('Unverified App', fuzzy=False)
    assert not view.resolve('Reject Me', fuzzy=False)
    assert not view.resolve('fixture@example.test', fuzzy=False)
    with graph._db() as db:
        assert {r['source'] for r in db.execute('SELECT DISTINCT source FROM entity_sources')} == {
            'college', 'island_projects', 'phone_places', 'coaching_goals', 'teacher'}
        assert all(r['confirmed'] == 1 and r['confidence'] == 1 for r in db.execute('SELECT * FROM relations'))
        physics = view.resolve('Physics', ('course',))[0]
        assert any(e['relation'] == 'enrolled_in' and e['to_id'] == physics['id'] for e in view.edges)
        before = db.execute('SELECT COUNT(*) FROM history').fetchone()[0]
    graph_sources.refresh()
    with graph._db() as db:
        assert db.execute('SELECT COUNT(*) FROM history').fetchone()[0] == before
    save(deadlines.path, [{**PHYSICS, 'due': '2026-11-24T19:30'}, DSA])
    revised = graph_sources.refresh()
    assert revised.resolve('Physics Lab Record')[0]['due'] == '2026-11-24T19:30'
    assert not revised.resolve('Physics Midterm Exam', fuzzy=False)
    assert '7:30 PM' in ask('what is due for Physics').message


def test_native_island_profile_projects_are_read_without_initializing_config(dataset):
    from services.friday_island_server import config as island_config
    path = island_config.config_path()
    graph_sources.refresh()
    assert not path.exists()
    native = island_config.IslandConfig(projects=[island_config.Project(id='native', name='Island Lab', path=str(dataset[1]))])
    # Use a distinct folder so the catalog treats this as a separate saved profile.
    folder = dataset[1] / 'native'
    folder.mkdir()
    native.projects[0].path = str(folder)
    raw = native.model_dump_json()
    path.write_text(raw, encoding='utf-8')
    assert graph_sources.refresh().resolve('Island Lab', fuzzy=False)
    assert path.read_text(encoding='utf-8') == raw


def test_aliases_ambiguity_and_t3_timetable_slot(dataset):
    assert ask("what is due for Prof Rao's course").message.startswith('Due for Prof Elena Rao')
    assert ask('who teaches D S A').message.startswith('Dr Maya Sen')
    assert ask('who teaches Physcs').message.startswith('Prof Elena Rao')
    question = ask('which project is lab record for').message
    assert question.startswith('Which one do you mean?')
    assert 'Physics Lab Record (Physics)' in question
    assert 'DSA Lab Record (Data Structures and Algorithms)' in question
    assert ask('alias Physics as Waves Lab').success
    assert command_slots.course('Waves Lab') == 'Physics'
    assert ask('what time is my Waves Lab class today').message.startswith('Physics on Monday, 23 Nov')
    chemistry = dict(subject='Chemistry', faculty='Prof Nita Rao')
    save(college_store.path('subjects.json'), {**SUBJECTS, 'chemistry': chemistry})
    question = ask('what is due for Prof Rao').message
    assert question.startswith('Which one do you mean?') and 'Prof Nita Rao' in question and 'Prof Elena Rao' in question


def test_ten_fixture_questions(dataset):
    approve('Rahul is my lab partner for Physics')
    approve('Physics Lab Record is part of Optics Lab')
    approve('Physics Midterm Exam blocks Optics Lab')
    approve('project Optics Lab uses app Obsidian')
    approve('app Obsidian is related to topic Notebook links')
    approve('topic Notebook links is related to topic Fourth Hop')

    samples = [
        ('what is due for Physics', 'Due for Physics — Physics Lab Record — tomorrow at 5:00 PM. '
                                    'Physics Midterm Exam — Thursday 26 Nov at 9:00 AM.'),
        ("what is due for Prof Rao's course", 'Due for Prof Elena Rao — Physics Lab Record — tomorrow at 5:00 PM. '
                                             'Physics Midterm Exam — Thursday 26 Nov at 9:00 AM.'),
        ('what is due for DSA', 'Due for Data Structures and Algorithms — DSA Lab Record — Wednesday 25 Nov at 6:00 PM.'),
        ('who teaches Physics', 'Prof Elena Rao teaches Physics.'),
        ('who teaches DSA', 'Dr Maya Sen teaches Data Structures and Algorithms.'),
        ('which project is physics lab record for', 'Physics Lab Record is for optics lab.'),
        ('how do I know Rahul', 'You recorded Rahul as lab partner for Physics.'),
        ('what do I have with Rahul', 'You recorded Rahul as lab partner for Physics. Saved for those courses — '
                                      'Physics Lab Record — tomorrow at 5:00 PM. Physics Midterm Exam — Thursday 26 Nov at 9:00 AM.'),
        ('which project is DSA Lab Record for', 'I have no confirmed project for DSA Lab Record.'),
        ('what is connected to Physics Lab Record', 'Connected to Physics Lab Record — Physics (course), '
         'optics lab (project), A-12 (place), Prof Elena Rao (faculty), Physics Midterm Exam (exam), '
         'Rahul (person), Obsidian (app), Lab 7 (place), Notebook links (topic).'),
    ]
    for question, expected in samples:
        assert ask(question).message == expected


def test_inference_review_and_forget_cascade(dataset, monkeypatch):
    monkeypatch.setattr(whatsapp, 'load', lambda: pytest.fail('Contacts must stay outside graph routing.'))
    for message in ('note Optics Lab and Physics are on my list',
                    'note I revised Physics and planned Optics Lab',
                    'mention Physics came up while I worked on Optics Lab'):
        assert ask(message).success
    proposal = graph.proposals()[0]
    assert (proposal['source'], proposal['confidence'], proposal['confirmed']) == ('co_mentions', .65, 0)
    assert 'optics lab' not in ask('what is connected to Physics').message
    offered = ask('evening questions').message
    assert '65%' in offered and 'confirm graph link' in offered
    assert ask(f"confirm graph link {proposal['id']}").success
    assert 'optics lab' in ask('what is connected to Physics').message

    other = stage('Optics Lab is related to topic Folded Lens')
    assert ask('forget Optics Lab').success
    assert not graph.proposals()
    assert not ask(f'confirm graph link {other}').success
    assert not graph_sources.refresh().resolve('Optics Lab', fuzzy=False)
    with graph._db() as db:
        assert db.execute("SELECT COUNT(*) FROM relations WHERE id IN (?,?)", (proposal['id'], other)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM mentions').fetchone()[0] == 0
        assert 'optics lab' not in '\n'.join(db.iterdump())


def test_owner_statement_is_private_and_stays_pending(dataset):
    ident = stage('note Rahul is my lab partner for Physics')
    assert ask('how do I know Rahul').success is False
    assert notes.load() == []
    assert 'Rahul' in ask('read my notes').message
    assert not notes.briefing_line()
    assert ask('forget Rahul').success  # A pending-only entity has a forget path.
    assert not ask(f'confirm graph link {ident}').success
    assert not graph.proposals()
    assert ask('forget Rahul').message == 'I have no graph entity by that name.'
    assert asyncio.run(graph_commands.try_command('forget my phone', now=NOW)) is None


@pytest.mark.parametrize('prefix', ['type ', 'message ', 'say ', 'email ', 'forward '])
def test_routed_payload_is_not_treated_as_a_person_statement(dataset, prefix):
    message = prefix + 'Rahul is my lab partner for Physics'
    assert asyncio.run(graph_commands.try_command(message, now=NOW)) is None
    assert not graph.proposals()


def test_briefings_goals_and_preparation_only_use_confirmed_graph(dataset):
    from plugins.briefings.content import Builder
    from services.schedule_adapter import ScheduleAdapter

    definitions = dict(title='Physics practice', target=10, unit='problems', deadline='2026-12-01',
                       cadence=None, source={'kind': 'manual'}, review_window=dict(day=6, start='18:00', end='21:00'))
    goal = goals_sources.save(goals._memory(), definitions, 'Fixture commitment.', now=NOW)
    exams = Builder(SimpleNamespace(get_service=lambda name: ScheduleAdapter(now=lambda: NOW)), now=lambda: NOW)
    pending = stage('Physics Midterm Exam blocks Optics Lab')
    assert 'optics lab' not in exams.due(morning=True)
    assert ask(f'confirm graph link {pending}').success
    assert 'Physics Midterm Exam blocks optics lab.' in exams.due(morning=True)
    approve('Physics Lab Record is part of Optics Lab')
    assert 'optics lab project folder' in anticipation.prepare_work(PHYSICS)
    assert 'make a revision pack for Data Structures and Algorithms' in anticipation.prepare_work(DSA)
    approve('goal Physics practice is for course Physics')
    approve('goal Physics practice is related to project Optics Lab')
    progress = goals.handle(f"goal {goal['id']} progress", now=NOW)
    assert 'Connected to Physics, optics lab.' in progress['text']


def test_p5_marks_only_explicit_channels_without_identity_or_content(dataset):
    assert ask('mark Rahul as important').success
    assert graph_sources.priority_packages(['com.example.default']) == ['com.example.default']
    assert ask('mark Rahul as important on com.example.labchat').success
    vip = graph_sources.priority_packages()
    assert vip == ['com.example.labchat']
    assert triage.score('com.example.labchat', 'msg', 1, 'class', vip=vip)['allow']
    assert not triage.score('com.example.other', 'msg', 1, 'class', vip=vip)['allow']
    assert ask('unmark Rahul as important').success
    assert not graph_sources.priority_packages()


def test_export_and_chat_voice_bypass_gateway_and_history(dataset, monkeypatch):
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    from providers import failover
    from services.files.extract import is_private
    from services.remote.context import origin_scope

    calls = []

    async def unexpected(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('Graph facts are local.')

    monkeypatch.setattr(failover, 'complete_with_failover', unexpected)
    approve('Rahul is my lab partner for Physics')
    api = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    response = api.post('/api/v1/chat', json={'message': 'How do I know Rahul?'}).json()
    assert response['private'] and response['provider'] == 'local' and 'lab partner' in response['response']
    response = asyncio.run(voice._reply('What do I have with Rahul?', voice.VoiceRequest(speak=False)))
    assert response.private and not response.transcription and 'Rahul' in response.response
    assert not calls
    assert 'Rahul' not in str(chat._memory.get_recent_history())
    assert 'Rahul' in api.get('/api/v1/mind/life-graph').json()['text']
    assert api.get('/api/v1/mind/life-graph').headers['cache-control'] == 'no-store'
    with origin_scope(True):
        denied = asyncio.run(intent.try_system_action('how do I know Rahul?', 'ollama'))
    assert not denied.success and 'Rahul' not in denied.message
    receipt = ask('export my graph')
    export = graph.path.with_name('life_graph_export.json')
    assert receipt.success and export.name in receipt.message
    data = json.loads(export.read_text(encoding='utf-8'))
    assert any(row['name'] == 'Rahul' for row in data['entities'])
    assert is_private(export) and is_private(notes._private_path()) and is_private(graph.path)


def test_explicit_model_wording_uses_only_counts(dataset, monkeypatch):
    from providers import failover
    from providers.base_provider import ProviderResponse

    sent = []

    async def outline(provider, messages, prompt, _limit, **options):
        sent.append((json.loads(messages[0].content), prompt, options))
        return ProviderResponse('From your graph.', 'ollama', 'fixture')

    monkeypatch.setattr(failover, 'complete_with_failover', outline)
    assert ask('turn graph model wording on').success
    assert ask('who teaches Physics').success
    assert not sent
    monkeypatch.setattr(config, 'FRIDAY_LLM', 'on')
    assert ask('who teaches Physics').message == 'From your graph. Prof Elena Rao teaches Physics.'
    counts, prompt, options = sent[0]
    assert all(kind in {'person', 'course', 'faculty', 'assignment', 'exam', 'project', 'place', 'app', 'topic', 'goal'}
               and type(amount) is int for kind, amount in counts.items())
    assert 'Physics' not in prompt and 'Rao' not in prompt and options['purpose'] == 'wording'


def test_pending_evening_offer_uses_local_budget_delivery(dataset, monkeypatch):
    from services.presence import delivery

    ident = stage('Rahul is my lab partner for Physics')
    shown = []

    async def deliver(text, kind, now, **options):
        shown.append((text, kind, options))
        return True

    monkeypatch.setattr(delivery, 'submit', deliver)
    assert asyncio.run(evening.offer_graph(NOW))
    assert 'Rahul' in shown[0][0]
    assert shown[0][1:] == ('graph_question', {'key': f'proposal:{ident}', 'local_only': True})
    assert not graph.view().resolve('Rahul', fuzzy=False)
    assert ask(f'reject graph link {ident}').success
    assert not asyncio.run(evening.offer_graph(NOW))
