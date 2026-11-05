"""Presentation and offline HTTP behavior without Tk or external services."""
from datetime import datetime
import io
from urllib.error import HTTPError, URLError

import pytest

from interfaces.college import viewmodel as vm
from interfaces.college.client import Client, Error

NOW = datetime(2030, 1, 7, 8)


@pytest.mark.parametrize('due,done,expected', [('2030-01-07T07:00', False, 'Overdue'),
    ('2030-01-07T08:00', False, 'Now'), ('2030-01-07T08:20', False, 'In 20 min'),
    ('2030-01-07T10:30', False, 'In 2h 30m'), ('2030-01-09T08:00', False, 'In 2 days'),
    ('invalid', False, 'Date unavailable'), ('2030-01-06T00:00', True, 'Done')])
def test_countdowns(due, done, expected):
    assert vm.countdown(due, NOW, done) == expected


@pytest.mark.parametrize('url,allowed', [('https://class.example.edu/path', True), ('http://localhost/class', True),
    ('file:///private', False), ('javascript:alert(1)', False), ('https://user:password@example.edu', False), ('bad', False)])
def test_join_url_is_http_only(url, allowed):
    assert vm.safe_join(url) is allowed


def test_grid_filter_and_deadline_payload_are_plain_functions():
    row = {'id': 'd1', 'subject': 'DBMS', 'what': 'DBMS task', 'kind': 'homework', 'due': '2030-01-08T17:00', 'done': False, 'venue': 'Room A'}
    assert vm.filtered([row], 'dbms', 'Open', 'homework') == [row]
    assert vm.filtered([row], status='Done') == []
    value = vm.payload('deadlines', vm.defaults('deadlines', row), row)
    assert value['due'] == row['due'] and value['venue'] == 'Room A'
    grid, cells = vm.grid_rows([{'id': 'slot-0', 'day': 'monday', 'start': '09:00', 'end': '10:00', 'subject': 'DBMS'}])
    assert grid[0][1][1] == 'DBMS' and cells[('0', 'monday')] == 'slot-0'


def test_client_offline_and_invalid_json_shape_are_actionable(monkeypatch):
    client = Client()
    def offline(*args, **kwargs):
        raise URLError('Synthetic offline')
    monkeypatch.setattr(client.opener, 'open', offline)
    with pytest.raises(Error, match='backend is not running'):
        client.load('overview')
    monkeypatch.setattr(client.opener, 'open', lambda *a, **kw: io.BytesIO(b'[]'))
    with pytest.raises(Error, match='unreadable response'):
        client.load('overview')


def test_client_409_keeps_status_and_404_requests_restart(monkeypatch):
    client = Client()
    def conflict(*args, **kwargs):
        raise HTTPError('http://127.0.0.1/', 409, 'Conflict', {}, io.BytesIO(b'{"message":"Changed elsewhere"}'))
    monkeypatch.setattr(client.opener, 'open', conflict)
    with pytest.raises(Error) as result:
        client.load('events')
    assert result.value.status == 409 and str(result.value) == 'Changed elsewhere'
    def old_backend(*args, **kwargs):
        raise HTTPError('http://127.0.0.1/', 404, 'Missing', {}, io.BytesIO(b'{}'))
    monkeypatch.setattr(client.opener, 'open', old_backend)
    with pytest.raises(Error, match='Restart FRIDAY'):
        client.load('events')


def test_client_rejects_nonlocal_base_url():
    with pytest.raises(ValueError, match='local'):
        Client('http://remote.example:8000')
