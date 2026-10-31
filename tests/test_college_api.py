"""College API contract, authoritative validation and unchanged local-only guards."""
from fastapi.testclient import TestClient
import pytest

from interfaces.api.app import create_app
from services.college import parsers
from services.proactive import deadlines, timetable
from test_college_uploads import CSV, fixture_bytes


@pytest.fixture
def client():
    return TestClient(create_app(), base_url='http://127.0.0.1:8000')


def test_all_catalogs_and_overview_are_available_without_live_data(client):
    for section in ('timetable', 'subjects', 'deadlines', 'exams', 'events', 'uploads'):
        result = client.get('/api/v1/college/' + section)
        assert result.status_code == 200, result.text
        assert len(result.json()['revision']) == 64
        assert result.headers['cache-control'] == 'no-store'
    home = client.get('/api/v1/college/overview')
    assert home.status_code == 200 and home.json()['next_class'] is None


def test_revision_and_value_validation_errors_share_envelope(client):
    data = client.get('/api/v1/college/events').json()
    value = {'title': 'Synthetic meetup', 'date': '2030-01-12', 'start': '10:00', 'end': '11:00'}
    first = client.put('/api/v1/college/events', json={'revision': data['revision'], 'value': value})
    assert first.status_code == 200, first.text
    stale = client.put('/api/v1/college/events', json={'revision': data['revision'], 'value': value})
    assert stale.status_code == 409
    invalid = client.put('/api/v1/college/events', json={'revision': first.json()['revision'], 'value': {**value, 'end': '09:00'}})
    malformed = client.put('/api/v1/college/events', json={'revision': 'bad', 'value': value, 'path': 'C:/untrusted'})
    assert invalid.status_code == malformed.status_code == 422
    for response in (stale, invalid, malformed):
        assert set(response.json()) == {'error', 'message', 'status_code'}
        assert response.json()['status_code'] == response.status_code


@pytest.mark.parametrize('value', [
    {'day': 'someday', 'start': '09:00', 'end': '10:00', 'subject': 'DBMS'},
    {'day': 'monday', 'start': '24:00', 'end': '25:00', 'subject': 'DBMS'},
    {'day': 'monday', 'start': '06:00', 'end': '05:00', 'subject': 'DBMS'},
    {'day': 'monday', 'start': '09:00', 'end': '10:00', 'subject': '', 'faculty': 'Wrong store'},
])
def test_timetable_rejects_invalid_or_extra_fields(client, value):
    data = client.get('/api/v1/college/timetable').json()
    response = client.put('/api/v1/college/timetable', json={'revision': data['revision'], 'value': value})
    assert response.status_code == 422
    assert timetable.load() == []


def test_raw_upload_confirm_flow_and_no_path_api(client):
    staged = client.post('/api/v1/college/uploads?filename=test.csv', content=CSV)
    assert staged.status_code == 200, staged.text
    data = staged.json()
    assert timetable.load() == []
    body = {'rows': data['rows'], 'revision': data['revision'], 'mode': 'merge'}
    preview = client.post('/api/v1/college/uploads/' + data['token'] + '/preview', json=body)
    assert preview.status_code == 200 and preview.json()['valid']
    confirmed = client.post('/api/v1/college/uploads/' + data['token'] + '/confirm', json={**body, 'review': preview.json()['review']})
    assert confirmed.status_code == 200, confirmed.text
    assert timetable.load()[0]['subject'] == 'DBMS'
    result = client.post('/api/v1/college/uploads', json={'path': 'C:/private/schedule.xlsx'})
    assert result.status_code == 422


@pytest.mark.parametrize('filename', ['../escape.csv', 'C:\\temp\\table.csv', 'file.csv:stream', '/table.csv'])
def test_upload_filename_path_traversal_is_refused(client, filename):
    response = client.post('/api/v1/college/uploads', params={'filename': filename}, content=CSV)
    assert response.status_code == 400
    assert response.json()['error'] == 'validation_error'


def test_upload_size_spoofed_magic_and_unsafe_delete(client, monkeypatch):
    response = client.post('/api/v1/college/uploads?filename=spoof.png', content=CSV)
    assert response.status_code == 400
    monkeypatch.setattr(parsers, 'MAX_BYTES', 16)
    response = client.post('/api/v1/college/uploads?filename=large.csv', content=CSV)
    assert response.status_code == 413
    response = client.request('DELETE', '/api/v1/college/uploads/not-an-id', json={'id': 'not-an-id', 'revision': 'a' * 64})
    assert response.status_code == 400


def test_corrupt_store_is_refused_without_dropping_rows(client):
    timetable.path.write_text('["corrupted entry"]')
    response = client.get('/api/v1/college/timetable')
    assert response.status_code == 503
    assert timetable.path.read_text() == '["corrupted entry"]'


def test_api_security_middleware_and_no_cors_remain(client):
    origin = client.get('/api/v1/college/overview', headers={'Origin': 'https://untrusted.example'})
    assert origin.status_code == 403
    host = client.get('/api/v1/college/overview', headers={'Host': 'untrusted.example'})
    assert host.status_code == 400
    assert 'access-control-allow-origin' not in origin.headers
    remote = TestClient(create_app(), base_url='http://127.0.0.1:8000', client=('192.0.2.20', 1234))
    assert remote.get('/api/v1/college/overview').status_code == 403
