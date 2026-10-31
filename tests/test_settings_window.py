"""Real Tk widgets backed by synthetic catalogs, without owner-data/network I/O."""
import copy
import gc
import time
import tkinter as tk

import httpx
import pytest

from interfaces.settings import app as ui, launcher
from interfaces.settings.client import Error
from interfaces.tray import backend
from test_tray import friday, api, events


class FakeClient:
    def __init__(self):
        self.calls, self.failure = [], None
        self.data = {
            'contacts': [{'name': 'alice', 'value': {'number': '+447700900123'}},
                         {'name': 'dad', 'value': {'number': '+919876543210'}}],
            'routines': [{'name': 'work', 'value': {'steps': ['open vs code', 'set volume to 30']}}],
            'projects': [{'name': 'college', 'value': {'path': 'C:/Projects/college', 'repo': 'owner/college',
                          'sites': ['https://college.example'], 'resume': ['open the folder']}}],
            'modes': [{'name': 'study', 'value': {'steps': ['set volume to 25'], 'quiet': True}}],
            'screen_apps': [{'name': 'chrome', 'value': {'allowed': True}}],
        }

    def load(self, section):
        if self.failure:
            raise self.failure
        return {'items': copy.deepcopy(self.data[section]), 'revision': 'a' * 64, 'active': None}

    def save(self, section, original, name, value, revision):
        if self.failure:
            raise self.failure
        self.calls.append(('save', section, original, name, copy.deepcopy(value)))
        self.data[section] = [item for item in self.data[section] if item['name'] != original]
        self.data[section].append({'name': name, 'value': copy.deepcopy(value), 'revision': 'a' * 64, 'saved': True})
        return {**self.load(section), 'selected': name}

    def delete(self, section, name, revision):
        self.calls.append(('delete', section, name))
        self.data[section] = [item for item in self.data[section] if item['name'] != name]
        return self.load(section)


def spin(window, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.root.update()
        if predicate():
            return
        time.sleep(.01)
    pytest.fail('Tk request did not finish')


@pytest.fixture(scope='module')
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    gc.collect()  # Release retired test forms before another worker can collect them.
    root.destroy()


@pytest.fixture
def window(monkeypatch, tk_root):
    monkeypatch.setattr(ui.messagebox, 'askyesno', lambda *a, **kw: True)
    monkeypatch.setattr(ui.messagebox, 'showinfo', lambda *a, **kw: None)
    root = tk.Toplevel(tk_root)
    root.withdraw()
    window = ui.SettingsWindow(root, FakeClient())
    spin(window, lambda: window.editors['contacts'].data is not None)
    yield window
    spin(window, lambda: all(not editor.busy for editor in window.editors.values()))
    window.close()


def test_all_five_tabs_have_labeled_forms_and_native_controls(window):
    assert len(window.notebook.tabs()) == 5
    for index, (section, editor) in enumerate(window.editors.items()):
        window.notebook.select(index)
        spin(window, lambda: editor.data is not None)
        assert editor.form.controls['name'].winfo_exists()
        assert editor.form.read()[0] == window.client.data[section][0]['name']
    assert isinstance(window.editors['routines'].form.controls['steps'], tk.Text)
    assert 'path' in window.editors['projects'].form.controls
    assert 'quiet' in window.editors['modes'].form.controls
    assert window.client.calls == []


def test_screen_access_can_choose_allow_block_save_and_delete(window, monkeypatch):
    editor = window.editors['screen_apps']
    window.notebook.select(4)
    spin(window, lambda: editor.data is not None)
    editor.new()
    monkeypatch.setattr('interfaces.settings.forms.filedialog.askopenfilename',
                        lambda **kw: 'C:/Apps/terminal.exe')
    editor.form.controls['_browse'].invoke()
    assert editor.form.read()[0] == 'terminal.exe'
    editor.form.variables['allowed'].set(False)
    editor.save()
    spin(window, lambda: not editor.busy)
    assert window.client.calls[-1] == ('save', 'screen_apps', None, 'terminal.exe', {'allowed': False})
    editor.form.variables['allowed'].set(True)
    editor.save()
    spin(window, lambda: not editor.busy)
    assert window.client.calls[-1][-1] == {'allowed': True}
    editor.delete()
    spin(window, lambda: not editor.busy)
    assert window.client.calls[-1] == ('delete', 'screen_apps', 'terminal.exe')


def test_filter_new_save_rename_and_delete_use_structured_values(window):
    editor = window.editors['contacts']
    editor.search.set('dad')
    window.root.update()
    assert editor.list.get_children() == ('dad',)
    editor.search.set('')
    editor.new()
    editor.form.variables['name'].set('friend')
    editor.form.variables['number'].set('+447700900456')
    editor.save()
    spin(window, lambda: not editor.busy)
    assert window.client.calls[-1] == ('save', 'contacts', None, 'friend', {'number': '+447700900456'})
    assert editor.original == 'friend' and not editor.dirty()
    editor.form.variables['name'].set('best friend')
    editor.save()
    spin(window, lambda: not editor.busy)
    assert editor.original == 'best friend'
    editor.delete()
    spin(window, lambda: not editor.busy)
    assert window.client.calls[-1] == ('delete', 'contacts', 'best friend')


def test_conflict_preserves_draft_and_reload_requires_discard(window, monkeypatch):
    editor = window.editors['contacts']
    editor.form.variables['number'].set('+447700900999')
    window.client.failure = Error('Settings changed elsewhere. Reload before saving; draft kept.', 409)
    editor.save()
    spin(window, lambda: not editor.busy)
    assert editor.form.read()[1]['number'] == '+447700900999'
    assert editor.dirty() and 'changed elsewhere' in editor.message.cget('text')
    monkeypatch.setattr(ui.messagebox, 'askyesno', lambda *a, **kw: False)
    editor.reload()
    assert not editor.busy and editor.dirty()
    monkeypatch.setattr(ui.messagebox, 'askyesno', lambda *a, **kw: True)
    window.client.failure = None
    editor.reload()
    spin(window, lambda: not editor.busy)
    assert not editor.dirty() and editor.form.read()[1]['number'] == '+447700900123'


def test_cancel_selection_from_a_new_draft_clears_highlight(window, monkeypatch):
    editor = window.editors['contacts']
    editor.new()
    editor.form.variables['name'].set('unsaved')
    monkeypatch.setattr(ui.messagebox, 'askyesno', lambda *a, **kw: False)
    editor.list.selection_set('dad')
    window.root.update()
    assert editor.original is None and not editor.list.selection()
    assert editor.form.read()[0] == 'unsaved'


def test_background_request_does_not_block_tk_event_processing(window):
    editor = window.editors['contacts']
    original = window.client.save
    def slow(*args):
        time.sleep(.15)
        return original(*args)
    window.client.save = slow
    ticks = []
    editor.save()
    window.root.after(10, lambda: ticks.append('responsive'))
    spin(window, lambda: bool(ticks))
    assert editor.busy
    spin(window, lambda: not editor.busy)


def test_empty_new_fields_require_a_name(window):
    contacts = window.editors['contacts']
    contacts.new()
    assert contacts.form.read() == ('', {'number': ''})
    contacts.save()
    assert not contacts.busy and 'Enter a name' in contacts.message.cget('text')


def test_offline_start_is_clear_and_retry_recovers(window):
    editor = window.editors['contacts']
    window.client.failure = Error('FRIDAY is not running.')
    editor.reload()
    spin(window, lambda: not editor.busy)
    assert 'not running' in editor.message.cget('text')
    assert 'unavailable' in window.connection.get()
    window.client.failure = None
    editor.reload()
    spin(window, lambda: not editor.busy)
    assert window.connection.get().startswith('Connected')


def test_http_detail_reaches_the_editor_without_echoing_validation_inputs(monkeypatch):
    response = httpx.Response(409, json={'detail': 'Settings changed elsewhere. Reload before saving.'})
    monkeypatch.setattr(backend.httpx, 'request', lambda *a, **kw: response)
    with pytest.raises(Error, match='Reload before saving'):
        backend._request('PUT', '/api/v1/customization/contacts', 2)
    response = httpx.Response(422, json={'detail': [{'input': 'private phone data'}]})
    with pytest.raises(Error) as error:
        backend._request('PUT', '/api/v1/customization/contacts', 2)
    assert 'private phone data' not in str(error.value)


def test_launcher_uses_an_argument_list_project_cwd_and_hidden_console(monkeypatch):
    calls = []
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *args, **kwargs: calls.append((args, kwargs)))
    launcher.launch()
    args, options = calls[0]
    assert args[0][-2:] == ['-m', 'interfaces.settings']
    assert options['cwd'] == launcher.Path(launcher.__file__).resolve().parents[2]
    assert options['creationflags'] == launcher.subprocess.CREATE_NO_WINDOW


def test_tray_exposes_customization_even_when_backend_is_offline(friday, monkeypatch):
    from test_tray import find, click
    calls = []
    monkeypatch.setattr(launcher, 'launch', lambda: calls.append('opened'))
    friday.online = False
    item = find(friday.icon.menu, 'Customize FRIDAY…')
    click(friday, item)
    assert calls == ['opened']


def test_old_backend_gets_actionable_restart_instructions(monkeypatch):
    from interfaces.settings.client import Client
    def old(*args, **kwargs):
        raise Error('Not Found', 404)
    monkeypatch.setattr(backend, '_request', old)
    with pytest.raises(Error, match='Restart FRIDAY'):
        Client().load('contacts')
