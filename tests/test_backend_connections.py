"""Local entry points share API configuration and bypass environment proxies."""
import importlib
import asyncio
import io
import json
from types import SimpleNamespace

import httpx
import pytest

from core.config import config
from interfaces.college.client import Client
from interfaces.college import launcher
from interfaces.settings.client import Client as SettingsClient
from interfaces.tray import backend
from services.automation.device_commands import match_device_command
from services.automation import intent


@pytest.mark.parametrize('payload', ['my history notes', 'clipboard item 3', 'Keep CAPS', 'hello to clipboard'])
def test_explicit_clipboard_write_treats_command_words_as_payload(payload):
    assert match_device_command(f'copy {payload} to clipboard') == {
        'type': 'system', 'action': 'write_clipboard', 'text': payload}


@pytest.mark.parametrize('payload', ['Keep CAPS', 'my history notes', 'clipboard item 3', 'mute and open chrome'])
def test_clipboard_payload_cannot_become_another_command(monkeypatch, payload):
    captured = []
    def execute(parsed, confirmed=False):
        captured.append(parsed)
        return intent.ActionResult(True, 'captured')
    monkeypatch.setattr(intent, '_execute', execute)
    result = asyncio.run(intent.try_system_action(f'copy {payload} to clipboard', 'ollama'))
    assert result.success
    assert captured == [{'type': 'system', 'action': 'write_clipboard', 'text': payload}]


def test_browser_cancel_shortcut_matches_the_normal_stop_control():
    from services.browser.commands import match_command
    assert match_command('\\b cancel') == match_command('browser cancel') == match_command('browser stop')


@pytest.mark.parametrize('caller', [backend.runtime_status, lambda: backend.chat('hello'),
    lambda: SettingsClient().load('projects')])
def test_all_desktop_requests_bypass_proxies(monkeypatch, caller):
    calls = []
    def request(method, url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={'response': 'hello'})
    monkeypatch.setattr(backend.httpx, 'request', request)
    caller()
    assert calls[0][0].startswith(backend.BASE_URL)
    assert calls[0][1]['trust_env'] is False


def test_college_client_and_launcher_share_configured_backend(monkeypatch):
    monkeypatch.setattr(config, 'API_HOST', 'localhost')
    monkeypatch.setattr(config, 'API_PORT', 8123)
    client = Client()
    seen = []
    def open_request(request, **kwargs):
        seen.append(request if isinstance(request, str) else request.full_url)
        return io.BytesIO(json.dumps({'service': 'F.R.I.D.A.Y'}).encode())
    monkeypatch.setattr(client.opener, 'open', open_request)
    monkeypatch.setattr(launcher, 'Client', lambda: client)
    def no_launch(*args, **kwargs):
        pytest.fail('Healthy configured backend must not be started again')
    monkeypatch.setattr(launcher.subprocess, 'Popen', no_launch)
    client.load('overview')
    launcher.ensure_backend()
    assert seen == ['http://localhost:8123/api/v1/college/overview', 'http://localhost:8123/health']
    assert Client('http://127.0.0.1:8765').base_url == 'http://127.0.0.1:8765'


def test_cli_uses_shared_configuration(monkeypatch):
    from interfaces.cli import friday
    monkeypatch.setattr(config, 'API_HOST', 'localhost')
    monkeypatch.setattr(config, 'API_PORT', 8123)
    original = friday.URL
    try:
        importlib.reload(friday)
        assert friday.URL == 'http://localhost:8123/api/v1/chat'
        monkeypatch.setattr(friday.urllib.request, 'build_opener',
            lambda handler: SimpleNamespace(open=lambda request, timeout: io.BytesIO(b'{"response":"connected"}')))
        assert friday.ask('hello') == 'connected'
    finally:
        friday.URL = original
