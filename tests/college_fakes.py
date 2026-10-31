"""Synthetic college API double for native tests/previews; never reads owner data."""
import copy
import threading
import time


class FakeClient:
    def __init__(self):
        self.calls, self.threads, self.failure = [], [], None
        self.delay, self.save_delay, self.revision = 0, 0, 'a' * 64
        self.data = {
            'timetable': [{'id': 'slot-0', 'day': 'monday', 'start': '09:00', 'end': '10:00', 'subject': 'DBMS'},
                          {'id': 'slot-1', 'day': 'monday', 'start': '11:00', 'end': '12:00', 'subject': 'Data Structures'},
                          {'id': 'slot-2', 'day': 'tuesday', 'start': '09:00', 'end': '10:00', 'subject': 'DBMS'},
                          {'id': 'slot-3', 'day': 'wednesday', 'start': '10:00', 'end': '11:00', 'subject': 'Operating Systems'},
                          {'id': 'slot-4', 'day': 'thursday', 'start': '11:00', 'end': '12:00', 'subject': 'Data Structures'},
                          {'id': 'slot-5', 'day': 'friday', 'start': '09:00', 'end': '10:00', 'subject': 'DBMS'}],
            'subjects': [{'id': 'dbms', 'subject': 'DBMS', 'faculty': 'Dr Mira Shah', 'room': 'B-204', 'email': 'mira@example.edu', 'notes': ''},
                         {'id': 'ds', 'subject': 'Data Structures', 'faculty': 'Prof Alex Rao', 'room': 'Lab 3', 'email': '', 'notes': ''},
                         {'id': 'os', 'subject': 'Operating Systems', 'faculty': 'Dr Sam Lee', 'room': 'A-106', 'email': '', 'notes': ''}],
            'deadlines': [{'id': 'd1', 'what': 'DBMS normalization worksheet', 'subject': 'DBMS', 'kind': 'homework',
                           'due': '2030-01-08T17:00', 'notes': 'Exercises 1–6', 'done': False, 'venue': ''},
                          {'id': 'd2', 'what': 'Data Structures lab report', 'subject': 'Data Structures', 'kind': 'assignment',
                           'due': '2030-01-10T23:59', 'notes': '', 'done': False, 'venue': ''},
                          {'id': 'd3', 'what': 'Operating Systems reading', 'subject': 'Operating Systems', 'kind': 'homework',
                           'due': '2030-01-06T17:00', 'notes': '', 'done': True, 'venue': ''}],
            'exams': [{'id': 'e1', 'what': 'DBMS exam', 'subject': 'DBMS', 'kind': 'exam', 'due': '2030-01-17T09:00',
                       'date': '2030-01-17', 'time': '09:00', 'notes': 'Bring your student ID', 'venue': 'Main hall', 'done': False},
                      {'id': 'e2', 'what': 'Data Structures exam', 'subject': 'Data Structures', 'kind': 'exam', 'due': '2030-01-21T10:00',
                       'date': '2030-01-21', 'time': '10:00', 'notes': '', 'venue': 'B-201', 'done': False}],
            'events': [{'id': 'v1', 'title': 'Campus hackathon', 'date': '2030-01-12', 'start': '10:00', 'end': '18:00', 'location': 'Innovation lab', 'notes': 'Bring a laptop'},
                       {'id': 'v2', 'title': 'Project showcase', 'date': '2030-01-16', 'start': '14:00', 'end': '16:00', 'location': 'Auditorium', 'notes': ''}],
            'uploads': [{'id': '1' * 32, 'filename': 'spring-timetable.csv', 'size': 2048, 'extension': '.csv'}],
        }

    def check(self):
        self.threads.append(threading.get_ident())
        if self.delay:
            time.sleep(self.delay)
        if self.failure:
            raise self.failure

    def load(self, section):
        self.check()
        section = section.split('?')[0]
        if section == 'overview':
            following = {**self.data['timetable'][0], 'date': '2030-01-07', 'faculty': 'Dr Mira Shah',
                         'room': 'B-204', 'join_link': 'https://class.example.edu/dbms'}
            return {'now': '2030-01-07T08:00:00', 'current_class': None, 'next_class': following,
                    'today': [following, {**self.data['timetable'][1], 'date': '2030-01-07', 'faculty': 'Prof Alex Rao', 'room': 'Lab 3'}],
                    'due_soon': copy.deepcopy(self.data['deadlines'][:2]), 'exams': copy.deepcopy(self.data['exams']),
                    'events': copy.deepcopy(self.data['events']), 'cancellations': []}
        return {'revision': self.revision, 'items': copy.deepcopy(self.data[section]), 'effective': [], 'cancellations': []}

    def save(self, section, identifier, value, revision):
        self.check()
        if self.save_delay:
            time.sleep(self.save_delay)
        self.calls.append(('save', section, identifier, copy.deepcopy(value), revision))
        self.data[section] = [r for r in self.data[section] if r['id'] != identifier]
        self.data[section].append({'id': identifier or 'new-record', **value})
        return {**self.load(section), 'message': 'Changes saved.'}

    def delete(self, section, identifier, revision):
        self.check()
        self.calls.append(('delete', section, identifier, revision))
        self.data[section] = [r for r in self.data[section] if r['id'] != identifier]
        return self.load(section)

    def move_date(self, identifier, day, start, revision):
        self.check()
        self.calls.append(('move_date', identifier, day, start, revision))
        return {**self.load('timetable'), 'message': 'Dated class moved.'}

    def upload(self, filename):
        self.check()
        return {'token': '2' * 32, 'filename': 'synthetic-timetable.csv', 'revision': self.revision,
                'rows': [{'day': 'monday', 'start': '09:00', 'end': '10:00', 'subject': 'DBMS', 'room': None},
                         {'day': 'tuesday', 'start': '11:00', 'end': '12:00', 'subject': 'Data Structures', 'room': None}],
                'requires_vision': False, 'warnings': [[], ['Check subject spelling']],
                'notice': 'Synthetic editable preview. Nothing is saved before Confirm.'}

    def preview(self, token, rows, revision, mode='merge'):
        self.check()
        return {'valid': True, 'warnings': [[] for r in rows], 'revision': revision, 'review': 'b' * 64,
                'diff': {'added': copy.deepcopy(rows), 'removed': [], 'unchanged': 4}, 'message': 'Review the diff, then Confirm.'}

    def confirm(self, token, rows, revision, mode, review):
        self.check()
        if self.save_delay:
            time.sleep(self.save_delay)
        self.calls.append(('confirm', token, copy.deepcopy(rows), mode))
        return {'message': 'Upload confirmed.', 'uploads': self.load('uploads'), 'timetable': self.load('timetable')}

    def discard(self, token):
        self.check()
        self.calls.append(('discard', token))
        return {'message': 'Discarded.'}

    def delete_upload(self, identifier, revision):
        return self.delete('uploads', identifier, revision)

    def vision(self):
        self.check()
        return {'available': True, 'selected': {'provider': 'synthetic-provider', 'model': 'test-model'},
                'consent': 'c' * 64, 'notice': 'Only this test provider; no real inference.', 'reason': ''}

    def extract(self, token, consent, section=''):
        self.check()
        return self.upload('synthetic.png')
