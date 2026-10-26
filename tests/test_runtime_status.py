from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from services.automation import modes
from services.spotify import auth


def test_runtime_endpoint_reports_saved_mode_and_connection_without_ai(monkeypatch):
    modes.begin('gaming', None)
    monkeypatch.setattr(auth, 'is_configured', lambda: True)
    monkeypatch.setattr(auth, 'is_connected', lambda: True)
    client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    response = client.get('/api/v1/system/status')
    assert response.status_code == 200
    data = response.json()
    assert data['mode']['name'] == 'gaming'
    assert 'gaming' not in data
    assert data['spotify'] == {'configured': True, 'connected': True}
    assert 'token' not in response.text and 'client_id' not in response.text


def test_runtime_endpoint_default_is_normal_mode():
    client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    data = client.get('/api/v1/system/status').json()
    assert data['mode']['name'] == 'normal'


def test_runtime_endpoint_reports_unknown_when_mode_file_is_corrupt():
    modes.state_path.write_text('{broken', encoding='utf-8')
    client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    response = client.get('/api/v1/system/status')
    assert response.status_code == 200
    assert response.json()['mode']['name'] is None


def test_removed_optimizer_pages_and_api_are_unavailable():
    client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    for path in ('/gaming', '/gaming/profiles.js', '/api/v1/gaming/profiles'):
        assert client.get(path).status_code == 404
    for method in ('PUT', 'DELETE'):
        assert client.request(method, '/api/v1/gaming/profiles/gowr', json={}).status_code == 404
