"""Configuration CRUD shares storage/validation with commands, never execution."""
import asyncio
import copy
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from services import customization, settings_store
from services.activity import projects
from services.automation import intent, modes, routines, whatsapp
from services.automation.system_control import AutomationError


@pytest.fixture
def client():
    return TestClient(create_app(), base_url='http://127.0.0.1:8000')


def edit(client, section, name, value, original=None, revision=None):
    revision = revision or client.get('/api/v1/customization/' + section).json()['revision']
    return client.put('/api/v1/customization/' + section,
                      json={'name': name, 'value': value, 'original': original, 'revision': revision})


def remove(client, section, name, revision=None):
    revision = revision or client.get('/api/v1/customization/' + section).json()['revision']
    return client.request('DELETE', '/api/v1/customization/' + section, json={'name': name, 'revision': revision})


@pytest.mark.parametrize('section,value', [
    ('contacts', {'number': '98765 43210'}),
    ('routines', {'steps': ['open vs code', 'wait 2 seconds']}),
    ('modes', {'steps': ['set volume to 20'], 'quiet': True}),
])
def test_create_update_rename_and_delete_share_command_files(client, section, value):
    response = edit(client, section, 'daily setup', value)
    assert response.status_code == 200
    assert customization.SECTIONS[section].load()['daily setup']
    response = edit(client, section, 'renamed', value, original='daily setup')
    assert response.status_code == 200 and response.json()['selected'] == 'renamed'
    assert 'daily setup' not in customization.SECTIONS[section].load()
    assert remove(client, section, 'renamed').status_code == 200
    assert 'renamed' not in customization.SECTIONS[section].load()


def test_reading_tabs_does_not_initialize_config_files(client):
    for section in customization.SECTIONS:
        path = customization.SECTIONS[section].path
        assert not path.exists()
        response = client.get('/api/v1/customization/' + section)
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        assert not path.exists()


@pytest.mark.parametrize('section,bad', [
    ('contacts', []), ('contacts', {'mom': 9876543210}),
    ('routines', {'work': ['mute'], 'important': 'invalid'}),
    ('routines', {'work': [123]}), ('modes', {'work': {'steps': 'mute', 'quiet': True}}),
    ('projects', {'work': {'path': 12}}),
])
def test_broken_storage_is_preserved_on_read_and_mutation(client, section, bad):
    path = customization.SECTIONS[section].path
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(bad)
    path.write_text(raw, encoding='utf-8')
    assert client.get('/api/v1/customization/' + section).status_code == 503
    response = client.request('DELETE', '/api/v1/customization/' + section,
                              json={'name': 'work', 'revision': 'a' * 64})
    assert response.status_code == 503 and path.read_text(encoding='utf-8') == raw


@pytest.mark.parametrize('section,value', [
    ('contacts', {'number': 'call 9876543210'}), ('contacts', {'number': '123'}),
    ('routines', {'steps': []}), ('routines', {'steps': ['']}),
    ('routines', {'steps': [1]}), ('modes', {'steps': [], 'quiet': 'false'}),
    ('projects', {'path': '../outside'}),
])
def test_invalid_fields_never_write_settings(client, section, value):
    response = edit(client, section, 'bad', value)
    assert response.status_code in (400, 422)
    assert not customization.SECTIONS[section].path.exists()


def test_command_edits_and_name_collisions_reject_stale_drafts(client):
    original = client.get('/api/v1/customization/routines').json()['revision']
    routines.run_edit({'action': 'create_routine', 'routine': 'work', 'steps': ['mute']})
    response = edit(client, 'routines', 'work', {'steps': ['unmute']}, revision=original)
    assert response.status_code == 409 and 'Reload' in response.json()['detail']
    assert routines.load()['work'] == ['mute']
    assert edit(client, 'routines', 'other', {'steps': ['mute']}).status_code == 200
    assert edit(client, 'routines', 'work', {'steps': ['unmute']}, original='other').status_code == 409


def test_file_save_failure_preserves_bytes_and_removes_temporary_file(client, monkeypatch):
    assert edit(client, 'routines', 'work', {'steps': ['mute']}).status_code == 200
    before = routines.path.read_bytes()
    def broken(*args):
        raise OSError('Synthetic replacement failure')
    monkeypatch.setattr(settings_store.os, 'replace', broken)
    assert edit(client, 'routines', 'work', {'steps': ['unmute']}, original='work').status_code == 503
    assert routines.path.read_bytes() == before
    assert not list(routines.path.parent.glob('routines.json.*.tmp'))


def test_creating_routines_and_modes_cannot_execute_the_saved_commands(client, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail('Saving configuration executed an action')
    monkeypatch.setattr(intent, 'try_system_action', forbidden)
    monkeypatch.setattr(modes, 'begin', forbidden)
    assert edit(client, 'routines', 'work', {'steps': ['shutdown', 'message mom hi']}).status_code == 200
    assert edit(client, 'modes', 'work', {'steps': ['open vs code'], 'quiet': True}, original='work').status_code == 200
    assert modes.active() is None


def test_active_mode_cannot_be_deleted_or_renamed_but_preferences_are_future_only(client):
    modes.begin('work', 55)
    state = modes.active()
    assert remove(client, 'modes', 'work').status_code == 400
    assert edit(client, 'modes', 'renamed', {'steps': [], 'quiet': False}, original='work').status_code == 400
    assert edit(client, 'modes', 'work', {'steps': ['mute'], 'quiet': False}, original='work').status_code == 200
    assert modes.active() == state


@pytest.mark.parametrize('number', ['98765 43210', '00447700900123'])
def test_existing_phone_formats_round_trip_without_changing_country(client, number):
    whatsapp.path.parent.mkdir(parents=True, exist_ok=True)
    whatsapp.path.write_text(json.dumps({'mom': number}), encoding='utf-8')
    row = client.get('/api/v1/customization/contacts').json()['items'][0]
    assert row['value']['number'] == '+' + whatsapp.clean_number(number)
    assert edit(client, 'contacts', 'mom', row['value'], original='mom').status_code == 200
    assert whatsapp.load()['mom'] == whatsapp.clean_number(number)


def test_contact_edit_invalidates_pending_sends_in_both_scopes_and_fences_popped_send(client, monkeypatch):
    whatsapp.run_contacts({'action': 'save_contact', 'name': 'mom', 'number': '9876543210'})
    parsed = {'action': 'send_whatsapp', 'contact': 'mom', 'text': 'hello'}
    whatsapp.confirmation(parsed)
    for scope in (False, True):
        intent._pending[scope] = intent.PendingAction(copy.deepcopy(parsed), time.monotonic() + 120)
    assert edit(client, 'contacts', 'mom', {'number': '+44 7700 900123'}, original='mom').status_code == 200
    assert intent._pending == {}
    monkeypatch.setattr(whatsapp.os, 'startfile', lambda *a: pytest.fail('Contact was retargeted'))
    with pytest.raises(AutomationError, match='changed'):
        whatsapp.send(parsed, lambda: 'whatsapp')


def test_project_forms_preserve_metadata_refresh_activity_and_keep_folder(client, tmp_path, monkeypatch):
    from services.activity.log import activity_log
    folder = tmp_path / 'project'
    folder.mkdir()
    projects.path.parent.mkdir(parents=True, exist_ok=True)
    projects.path.write_text(json.dumps({'college': {'path': str(folder), 'repo': None,
        'sites': ['college.example'], 'custom_note': 'keep me'}}), encoding='utf-8')
    calls = []
    monkeypatch.setattr(activity_log, 'resort', lambda: calls.append('refresh'))
    row = client.get('/api/v1/customization/projects').json()['items'][0]
    row['value']['sites'].append('https://docs.example/work')
    response = edit(client, 'projects', 'college', row['value'], original='college')
    assert response.status_code == 200 and projects.load()['college']['custom_note'] == 'keep me'
    assert projects.project_of_row('web', 'chrome', 'docs.example', '', projects.load()) == 'college'
    info = {**projects.load()['college'], 'sites': ['http://localhost:3000', 'http://127.0.0.1:4000',
                                                  'http://[::1]:3000', 'https://docs.example/work']}
    assert projects.resume_sites('college', info, SimpleNamespace(project_domains=lambda *a: [])) == ['https://docs.example/work']
    assert remove(client, 'projects', 'college').status_code == 200
    assert calls == ['refresh', 'refresh'] and folder.is_dir()


def test_project_save_recount_failure_is_reported_as_saved_with_warning(client, tmp_path, monkeypatch):
    from services.activity.log import activity_log
    monkeypatch.setattr(activity_log, 'resort', lambda: (_ for _ in ()).throw(OSError('Synthetic recount failure')))
    response = edit(client, 'projects', 'college', {'path': str(tmp_path)})
    assert response.status_code == 200 and 'saved' in response.json()['warning']
    assert projects.load()['college']['path'] == str(tmp_path)


def test_project_change_invalidates_old_resume_proposal_and_expected_snapshot(client, tmp_path, monkeypatch):
    assert edit(client, 'projects', 'college', {'path': str(tmp_path), 'resume': ['open the folder']}).status_code == 200
    intent._ask_first({'action': 'resume_project', 'name': 'college'}, 'Resume it?')
    old = copy.deepcopy(intent._pending[False].parsed['_project_snapshot'])
    assert edit(client, 'projects', 'college', {'path': str(tmp_path), 'resume': ['run changed command']}, original='college').status_code == 200
    assert not intent.is_awaiting_confirmation()
    monkeypatch.setattr(projects.system, 'open_url', lambda *a: pytest.fail('Opened a changed project'))
    with pytest.raises(AutomationError, match='changed'):
        projects.start_resume('college', SimpleNamespace(), expected=old)


def test_nonlocal_clients_and_other_websites_cannot_edit(client):
    revision = client.get('/api/v1/customization/contacts').json()['revision']
    body = {'name': 'mom', 'revision': revision, 'value': {'number': '9876543210'}}
    response = client.put('/api/v1/customization/contacts', json=body, headers={'Origin': 'https://elsewhere.example'})
    assert response.status_code == 403
    remote = TestClient(create_app(), base_url='http://127.0.0.1:8000', client=('192.0.2.20', 50000))
    assert remote.get('/api/v1/customization/contacts').status_code == 403
    assert not whatsapp.path.exists()


@pytest.mark.parametrize('site', ['javascript:alert(1)', 'file:///C:/test', 'https://host:bad',
                                  'https://host:99999', 'https://user:password@host', 'https://bad host/'])
def test_invalid_project_sites_are_rejected_without_writing(client, tmp_path, site):
    response = edit(client, 'projects', 'college', {'path': str(tmp_path), 'sites': [site]})
    assert response.status_code in (400, 422) and not projects.path.exists()


def test_project_crud_relabels_existing_activity_rows(client, tmp_path):
    from services.activity.log import activity_log
    from datetime import datetime
    folder = tmp_path / 'calculus'
    folder.mkdir()
    activity_log._insert(at=datetime.now().isoformat(), kind='app', app='code', title='calculus - VS Code', duration_s=60)
    assert edit(client, 'projects', 'college', {'path': str(folder)}).status_code == 200
    def recorded_project():
        with activity_log._connect() as db:
            return db.execute('SELECT project FROM activity ORDER BY id LIMIT 1').fetchone()[0]
    assert recorded_project() == 'college'
    assert edit(client, 'projects', 'calculus work', {'path': str(folder)}, original='college').status_code == 200
    assert recorded_project() == 'calculus work'
    assert remove(client, 'projects', 'calculus work').status_code == 200
    assert recorded_project() is None


