"""Exercise every advertised slash expansion through the actual Island command bridge.

OS input and model/transport boundaries are doubled; service routing stays real.
"""
import asyncio
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from core.config import config
from interfaces.api.routes import chat
from providers.base_provider import ProviderResponse
from services.automation import intent
from services.files import assistant as files
from services.files.search import FileHit, Passage
from services.friday_island_server.config import IslandConfig
from services.friday_island_server.runtime import FridayRuntime
from services.friday_island_server.server import Bridge, Request

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = """
import { slashSuggestions, resolveSlash } from './src/slash-commands.ts';
const args = {open:'chrome',proj:'fixture',resume:'fixture',note:'fixture note',
  remind:'in 10 minutes to stretch',find:'fixture', 'open-file':'1', 'ask-files':'what is in the fixture',
  research:'fixture topic',copy:'Keep CAPS',type:'fixture text',press:'ctrl+s',volume:'30',brightness:'40',
  remember:'I prefer tea',scene:'study'};
console.log(JSON.stringify(slashSuggestions('/').map(item => {
  const name = item.text.trim().slice(1);
  const input = '/' + name + (args[name] ? ' ' + args[name] : '');
  return {name,input,...resolveSlash(input)};
})));
"""
CASES = json.loads(subprocess.check_output(['node', '--experimental-strip-types', '--input-type=module', '-e', INVENTORY],
                                         cwd=ROOT / 'island', text=True))


@pytest.mark.parametrize('case', CASES, ids=lambda row: row['input'])
def test_advertised_slash_command_reaches_its_service(case, monkeypatch, tmp_path, request):
    if case.get('view') or case.get('palette') or case['name'] == 'proj':
        assert case.get('view') or case.get('palette') or case['text'] == 'proj fixture'
        return  # Native panels/projects are covered by the browser and Rust checks.
    from services.browser.service import automation
    from services.friday_island_server import desktop_link
    from services.phone import commands as phone_commands
    from services.mind import language, replies
    monkeypatch.setattr(desktop_link, 'desktop', desktop_link.DesktopLink())
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(config, 'AI_WORDING_ENABLED', False)
    intent.cancel_pending_confirmation()
    captured = []

    def execute(parsed, confirmed=False):
        captured.append(parsed)
        return intent.ActionResult(True, 'Captured ' + parsed['action'])

    async def no_model(*args, **kwargs):
        pytest.fail('An advertised local slash command fell through to AI conversation: ' + case['input'])

    async def browser(message, provider):
        captured.append({'action': 'browser', 'text': message})
        return SimpleNamespace(success=True, message='Browser route', awaiting_reply=False)

    async def phone(message, provider):
        assert phone_commands.match_command(message)['action'] == 'phone_status'
        return intent.ActionResult(True, 'Phone route')

    monkeypatch.setattr(intent, '_execute', execute)
    monkeypatch.setattr(automation, 'handle', browser)
    monkeypatch.setattr(phone_commands, 'handle', phone)
    monkeypatch.setattr(chat, 'complete_with_failover', no_model)
    monkeypatch.setattr(language, 'answer', no_model)
    monkeypatch.setattr(replies, 'answer', no_model)
    if case['name'] in {'focus', 'pomodoro', 'scene', 'scenes'}:
        request.getfixturevalue('local_focus_scenes')
    file = tmp_path / 'fixture.txt'
    file.write_text('Fixture contents', encoding='utf-8')
    files.last_results.set([FileHit(str(file), file.name)])
    if case['name'] == 'ask-files':
        assert files.extract_file_question(case['text']) == 'what is in the fixture'
        monkeypatch.setattr(files, 'find_passages', lambda question: [Passage(str(file), file.name, 'Fixture contents')])
        async def file_answer(message, provider, search_context, screen):
            assert 'Fixture contents' in search_context
            return ProviderResponse(content='Fixture answer', provider='local', model='fixture-model', tokens_used=0)
        monkeypatch.setattr(replies, 'answer', file_answer)
    if case['name'] == 'resume':
        intent.projects.path.write_text(json.dumps({'fixture': {'path': str(tmp_path)}}), encoding='utf-8')
        monkeypatch.setattr(intent.projects, 'start_resume', lambda name, log: ('Opened fixture', []))
    frames = []
    class Socket:
        async def send(self, raw):
            frames.append(json.loads(raw))

    async def run():
        bridge = Bridge(runtime=FridayRuntime())
        await bridge.command(Socket(), Request(v=1, type='command', id='fixture', text=case['text']), IslandConfig())

    asyncio.run(run())
    assert frames and frames[-1]['type'] == 'command_result', frames
    if case['name'] == 'ask-files':
        assert frames[-1]['text'] == 'Fixture answer'
    elif case['name'] not in {'next', 'habit', 'todo'}:
        assert frames[-1].get('action_success') is not None, frames[-1]
    if case['name'] == 'copy':
        assert captured == [{'type': 'system', 'action': 'write_clipboard', 'text': 'Keep CAPS'}]


@pytest.fixture
def local_focus_scenes(tmp_path, monkeypatch):
    from scenes_support import make_scenes
    from plugins.focus.timer import Focus
    from services import plugin_runtime
    from services.plugin_api import PluginAPI

    host = make_scenes(tmp_path)
    api = PluginAPI(host.manager, 'focus', tmp_path / 'focus')
    focus = Focus(api)
    host.manager.services['focus'] = focus
    monkeypatch.setattr(plugin_runtime, '_manager', host.manager)
    yield host
    focus.close(); api.stop()
    host.engine.close(); host.api.stop(); host.manager.bus.close()
