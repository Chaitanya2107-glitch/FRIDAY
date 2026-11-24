import asyncio
from datetime import datetime

import pytest

from core.config import config
from services.automation import app_finder, command_words, intent, whatsapp
from services.proactive import deadlines, timetable


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 19, 14, tzinfo=tz)


DUE = [
    ('tell me what is due tomorrow', '2026-11-20'),
    ('hey friday, could you tell me what is due tmrw, please?', '2026-11-20'),
    ('whats due tmr', '2026-11-20'),
    ('what is due tommorow?', '2026-11-20'),
    ('um, what is due tomorrow?', '2026-11-20'),
    ('show me what is due on Friday', '2026-11-20'),
    ('what is due this Fri?', '2026-11-20'),
    ('could u show my deadlines for Friday?', '2026-11-20'),
    ('list deadlines 2026-11-20', '2026-11-20'),
    ('show me my deadlines on 20 November', '2026-11-20'),
    ('what do I have due on November 20?', '2026-11-20'),
    ('whast due 20/11?', '2026-11-20'),
    ('pls list deadlines Friday', '2026-11-20'),
    ('lsit my deadlines for tomorrow', '2026-11-20'),
    ('what is due today?', '2026-11-19'),
    ('what is due tonite', '2026-11-19'),
    ('what is due today at 6 pm?', '2026-11-19'),
    ('tell me what is due the day after tomorrow', '2026-11-21'),
    ('show deadlines for Mon', '2026-11-23'),
    ('what is due 25/11/2026?', '2026-11-25'),
]

MOVES = [
    ('push my physics homework to Friday', 'physics homework', '2026-11-20T23:59'),
    ('please move the physics homework to Fri', 'physics homework', '2026-11-20T23:59'),
    ('shift my physics homework until tomorrow', 'physics homework', '2026-11-20T23:59'),
    ('can u reschedule physics homework for tmrw?', 'physics homework', '2026-11-20T23:59'),
    ('postpone my physics homework to Monday', 'physics homework', '2026-11-23T23:59'),
    ('psuh physics homework to Saturday', 'physics homework', '2026-11-21T23:59'),
    ('posptone my lab report to the day after tomorrow', 'lab report', '2026-11-21T23:59'),
    ('reshedule my lab report for Fri 8 am', 'lab report', '2026-11-20T08:00'),
    ('could you shift my lab report to Friday at 18:45 please?', 'lab report', '2026-11-20T18:45'),
    ('change the deadline DSP quiz to tomorrow at noon', 'dsp quiz', '2026-11-20T12:00'),
    ('move deadline stats quiz to 2026-11-23 at 9am', 'stats quiz', '2026-11-23T09:00'),
    ('move my statistics assignment to 24 Nov at 11:15pm', 'statistics assignment', '2026-11-24T23:15'),
    ('move my design project to 21/11', 'design project', '2026-11-21T23:59'),
    ('push back the maths assignment to November 25 at 5pm', 'maths assignment', '2026-11-25T17:00'),
    ('postpone my chemistry exam to 2026-11-30', 'chemistry exam', '2026-11-30T23:59'),
    ('my history report deadline has moved to tmr', 'history report', '2026-11-20T23:59'),
    ('the optics report deadline was moved to Friday at 10am', 'optics report', '2026-11-20T10:00'),
    ('actually, my mechanics homework deadline changed from Wednesday to Fri', 'mechanics homework', '2026-11-20T23:59'),
    ('hey friday, shift the Physics homework to tonite at 8pm', 'physics homework', '2026-11-19T20:00'),
    ('move "Logic and Proof" assignment to Fri at 16:10', '"logic and proof" assignment', '2026-11-20T16:10'),
]

COURSES = [
    ('what time is my DBMS class tomorrow?', 'course_schedule', 'DBMS', 'tomorrow'),
    ('when is the database management systems lecture?', 'course_schedule', 'DBMS', 'today'),
    ('when is my d b m s class Fri?', 'course_schedule', 'DBMS', 'friday'),
    ('show me the time of my DBMS class for tmrw', 'course_schedule', 'DBMS', 'tomorrow'),
    ('hey friday, when’s my Physics class tonight?', 'course_schedule', 'Physics', 'tonight'),
    ('what time is the Physics class on Monday, please?', 'course_schedule', 'Physics', 'monday'),
    ('when is my Physics lecture in red timetable?', 'course_schedule', 'Physics', 'in red timetable'),
    ('when is the DBMS class on 2026-11-23?', 'course_schedule', 'DBMS', '2026-11-23'),
    ('who teaches DBMS?', 'course_faculty', 'DBMS', None),
    ('who teaches database management systems?', 'course_faculty', 'DBMS', None),
    ('who is the instructor for my Physics?', 'course_faculty', 'Physics', None),
    ('who is the teacher for DBMS?', 'course_faculty', 'DBMS', None),
    ('please, who is the faculty for the physics?', 'course_faculty', 'Physics', None),
    ('who teaches Thermodynamics?', 'course_faculty', None, None),
    ('when is my CS 404 class tomorrow?', 'course_schedule', None, 'tomorrow'),
]

APPS = [
    ('um, could you open the app called Chrome?', 'open_app', 'chrome'),
    ('just launch the browser please', 'open_app', 'chrome'),
    ('get the web browser running', 'open_app', 'chrome'),
    ('poen the app named Chrome', 'open_app', 'chrome'),
    ('opne the Google Chrome browser', 'open_app', 'chrome'),
    ('will u fire up Microsoft Edge?', 'open_app', 'edge'),
    ('please bring Edge to the front', 'open_app', 'edge'),
    ('could you launch the application named Calculator?', 'open_app', 'calculator'),
    ('load calc real quick', 'open_app', 'calculator'),
    ('start up note pad', 'open_app', 'notepad'),
    ('open the program called Notepad', 'open_app', 'notepad'),
    ('can you close the app named Chrome?', 'close_app', 'chrome'),
    ('hey friday, close Edge down', 'close_app', 'edge'),
    ('quit the Calculator app', 'close_app', 'calculator'),
    ('close the application named Notepad', 'close_app', 'notepad'),
]

PEOPLE = [
    ('um, could you text Mom I’ll be late?', 'mom', 'I’ll be late?'),
    ('message Mom on WhatsApp: Back at 6!', 'mom', 'Back at 6!'),
    ('whatsapp Dev Singh I sent the slides.', 'dev singh', 'I sent the slides.'),
    ('send a WhatsApp to Dev Singh saying Lab moved to 9!', 'dev singh', 'Lab moved to 9!'),
    ('tell my lab partner on WhatsApp: Bring the multimeter.', 'lab partner', 'Bring the multimeter.'),
    ('ping my lab partner that the lab is open', 'lab partner', 'the lab is open'),
    ('whastapp Mom on my way', 'mom', 'on my way'),
    ('message saved contact mom: Will you call?', 'mom', 'Will you call?'),
    ('whatsapp message to Dev Singh: I have the notes!', 'dev singh', 'I have the notes!'),
    ('message dev via whatsapp: Read this and call me.', 'dev', 'Read this and call me.'),
    ('text Dev Singh: Bring pens, paper, and glue.', 'dev singh', 'Bring pens, paper, and glue.'),
    ('kindly say this on WhatsApp', None, None),
    ('WhatsApp Mom', 'mom', ''),
    ('message Alex on WhatsApp: Hello', 'alex', 'Hello'),
    ('send a message to Dev on WhatsApp: Are you free?', 'dev', 'Are you free?'),
]

BATCHES = [
    ('push my physics homework to Friday and tell me what is due tomorrow', ('move_deadline', 'list_deadlines')),
    ('move my lab report to Monday; list deadlines for tmr', ('move_deadline', 'list_deadlines')),
    ('psuh physics homework to Fri, and then show my deadlines for today', ('move_deadline', 'list_deadlines')),
    ('open the app called chrome and then what is due tomorrow', ('open_app', 'list_deadlines')),
    ('when is my Physics class today and open the app named edge', ('course_schedule', 'open_app')),
    ('opne chrome, then move my Physics homework to Fri', ('open_app', 'move_deadline')),
    ('tell me what is due tomorrow and close chrome', ('list_deadlines', 'close_app')),
    ('move "Logic and Proof" assignment to Friday and then list my deadlines', ('move_deadline', 'list_deadlines')),
]

CLARIFICATIONS = [
    ('hey friday could you open the app, please?', 'Which app'),
    ('opne', 'Which app'),
    ('send a WhatsApp to', 'Who should I message'),
    ('push my homework to Friday', 'Which deadline'),
    ('move deadline to Friday', 'Which deadline'),
    ('remind me', 'what should I remind you about'),
    ('who teaches', 'Which course'),
]


@pytest.fixture(autouse=True)
def local(monkeypatch):
    monkeypatch.setattr(config, 'FRIDAY_LLM', 'off')
    monkeypatch.setattr(intent, 'datetime', Clock)
    monkeypatch.setattr(deadlines, 'datetime', Clock)
    monkeypatch.setattr(timetable, 'datetime', Clock)
    monkeypatch.setattr(intent.system, 'list_apps', lambda: ['chrome', 'notepad', 'edge', 'calculator'])
    monkeypatch.setattr(app_finder, 'find_app', lambda name: None)
    monkeypatch.setattr(whatsapp, 'load', lambda: {'mom': '15550000001', 'lab partner': '15550000002',
                                                 'dev': '15550000003', 'dev singh': '15550000004'})
    timetable._save([dict(day='friday', start='09:00', end='10:00', subject='Physics', room=None),
                     dict(day='friday', start='10:00', end='11:00', subject='DBMS', room=None)])
    timetable._save_subjects(['Database Management Systems'])


def parse(text):
    text = command_words.rephrase_command(text)
    return intent._match_local_step(text) or intent._match_local_step(intent._correct_local_typo(text) or '')


@pytest.mark.parametrize('sentence,day', DUE)
def test_due_date_slot(sentence, day):
    assert parse(sentence) == {'type': 'system', 'action': 'list_deadlines', 'day': day}


@pytest.mark.parametrize('sentence,reference,when', MOVES)
def test_deadline_move_slots(sentence, reference, when):
    action = parse(sentence)
    assert action['action'] == 'move_deadline' and action['reference'].casefold() == reference
    assert deadlines.parse_due(action['when'], Clock.now()).isoformat(timespec='minutes') == when


@pytest.mark.parametrize('sentence,action,course,day', COURSES)
def test_course_slots(sentence, action, course, day):
    parsed = parse(sentence)
    assert (parsed['action'], parsed['course'], parsed.get('day')) == (action, course, day)


@pytest.mark.parametrize('sentence,action,app', APPS)
def test_app_slots(sentence, action, app):
    parsed = parse(sentence)
    assert (parsed['action'], parsed['app_name']) == (action, app)


@pytest.mark.parametrize('sentence,contact,body', PEOPLE)
def test_recipient_slots_keep_payload(sentence, contact, body):
    parsed = parse(sentence)
    if contact is None:
        assert parsed is None
    else:
        assert (parsed['action'], parsed['contact'], parsed['text']) == ('send_whatsapp', contact, body)


@pytest.mark.parametrize('sentence,actions', BATCHES)
def test_local_batch(sentence, actions):
    assert tuple(item['action'] for item in intent._local_multi_plan(command_words.rephrase_command(sentence))) == actions


@pytest.mark.parametrize('sentence,question', CLARIFICATIONS)
def test_local_clarification(sentence, question):
    result = asyncio.run(intent.try_system_action(sentence, 'ollama'))
    assert result and not result.success and question in result.message
