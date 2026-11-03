"""Real Chromium and authenticated transport; isolated fixture runtime and native IPC."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from playwright.async_api import async_playwright, expect
from websockets.asyncio.server import serve
from services.friday_island_server.config import load_config
from services.friday_island_server.plugins import Registry, CollegePlugin
from services.friday_island_server.server import Bridge, ORIGINS
from services.mind.cognition import cognition

ROOT = Path(__file__).resolve().parents[2]


class Runtime:
    def __init__(self):
        self.commands, self.actions, self.events = [], [], []
        self.last = 0
        self.listening = False
        self.release = asyncio.Event()
        self.automation = {'active': False, 'state': 'idle'}
        self.action_release = asyncio.Event()

    async def command(self, text, owner, target):
        self.commands.append(text)
        if text == 'slow': await self.release.wait()
        if text == 'private fixture':
            return {'ok': True, 'text': 'Fixture private response', 'private': True}
        if text == 'work fixture':
            return {'ok': True, 'text': 'Report saved.', 'action_success': True}
        if text == 'long fixture':
            return {'ok': True, 'text': '\n'.join(f'{i}. Detailed result for the fixture report.' for i in range(28))}
        return {'ok': True, 'text': f'FRIDAY handled: {text}', 'awaiting_reply': text == 'ask fixture'}

    async def action(self, action, value):
        self.actions.append(action)
        if action == 'notification': await self.action_release.wait()
        if action == 'listen': self.listening = not self.listening
        if action == 'voice_stop': self.listening = False
        return {'ok': True, 'text': 'Requested'}

    async def snapshot(self, since):
        return {'backend': True, 'epoch': 'fixture', 'last': self.last, 'provider': 'ollama',
                'body': {'listening': self.listening, 'thinking': False, 'speaking': False},
                'desktop': {'connected': True, 'wake': False, 'conversation': False, 'speak': True,
                            'speak_typed': False, 'body': False, 'owned': True, 'message': 'Ready'},
                'system': {'mode': {'name': 'normal'}, 'screen_watch': {'state': 'off'}},
                'automation': self.automation,
                'events': [row for row in self.events if since is not None and row['id'] > since]}

    async def history(self): return {'items': []}
    def disconnect(self, owner): pass
    def pending(self): return False
    def event(self, kind, text):
        self.last += 1
        self.events.append({'id': self.last, 'kind': kind, 'text': text, 'title': 'FRIDAY', 'at': 1, 'buttons': []})


async def main():
    with tempfile.TemporaryDirectory() as directory, patch.object(cognition, 'path', Path(directory) / 'mind.db'):
        path = Path(directory) / 'config.json'
        config = load_config(path)
        runtime = Runtime()
        next_class = {'subject': 'Fixture class', 'start': '10:30'}
        registry = Registry([CollegePlugin(lambda: dict(next_class))])
        bridge = Bridge(path, registry=registry, runtime=runtime)
        async with serve(bridge.handle, '127.0.0.1', 0, origins=ORIGINS) as server:
            sample = config.model_dump()
            sample['connection']['port'] = server.sockets[0].getsockname()[1]
            script = """
            globalThis.isTauri = true;
            window.fixture = SAMPLE;
            window.starts = 0;
            window.targetClears = 0;
            window.nativeModes = []; window.regionWidths = [];
            const callbacks = new Map(), listeners = new Map(); let next = 0;
            window.__emit = (event, payload) => listeners.get(event)?.({event,payload});
            window.__TAURI_INTERNALS__ = {
              transformCallback(callback) { callbacks.set(++next,callback); return next; },
              unregisterCallback(id) { callbacks.delete(id); },
              async invoke(cmd,args={}) {
                if (cmd==='get_config'||cmd==='reload_config') return structuredClone(window.fixture);
                if (cmd==='save_config') {window.fixture=structuredClone(args.next);window.fixture.revision++;return structuredClone(window.fixture);}
                if (cmd==='runtime_status') return {mode:'rest',hotkey_errors:[],max_width:720,max_height:740,reduce_motion:true};
                if (cmd==='set_mode') {window.nativeModes.push(args.mode);return;}
                if (cmd==='set_regions') {window.regionWidths.push(args.width);return;}
                if (cmd==='execution_target') return null;
                if (cmd==='clear_execution_target') {window.targetClears++; return;}
                if (cmd==='start_friday') {window.starts++;return;}
                if (cmd==='startup_status') return {phase:'external',error:'',owned_pid:null,isolated:true,login_enabled:false};
                if (cmd==='desktop_status') return {battery:null,media:null};
                if (cmd==='app_index_status'||cmd==='rescan_apps') return {count:0,scanning:false,updated_at:1,errors:[]};
                if (cmd==='search_apps') return [];
                if (cmd==='local_command') return {ok:false,text:'No app found'};
                if (cmd==='plugin:event|listen') {listeners.set(args.event,callbacks.get(args.handler));return ++next;}
                if (cmd==='plugin:event|unlisten') return;
                throw Error('Unexpected fixture native command '+cmd);
              }
            };
            """.replace('SAMPLE', json.dumps(sample))
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                page = await browser.new_page(viewport={'width': 760, 'height': 800})
                await page.clock.install()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                await page.add_init_script(script)
                await page.goto('http://127.0.0.1:1420')
                await page.wait_for_function("document.querySelector('.surface')?.classList.contains('offline')===false")
                surface = page.locator('.surface')
                reply = page.locator('.capsule-reply-text')
                async def acknowledge():
                    await page.get_by_role('button', name='Acknowledge reply').click()
                    await page.mouse.move(0, 700)
                async def summon():
                    await page.evaluate("window.__emit('hotkey','expand')")
                    await page.get_by_role('button', name='FRIDAY', exact=True).first.click()
                await summon()
                await expect(page.locator('.friday-status')).to_have_text('FRIDAY ready')
                command = page.get_by_role('combobox', name='FRIDAY command')
                async def submit(text):
                    if not await command.is_visible(): await page.evaluate("window.__emit('hotkey','expand')")
                    await command.fill(text); await command.press('Enter'); await expect(page.locator('input.command')).to_be_enabled()
                await command.fill('/')
                assert await page.get_by_role('option').count() > 40
                assert await page.locator('.suggestions').evaluate('node=>node.scrollHeight>node.clientHeight')
                await page.get_by_role('option').filter(has_text='/lock').get_by_role('button').click()
                await expect(command).to_have_value('/lock')
                assert runtime.commands == [], 'Choosing a slash entry executed it without Enter'
                await submit('/note fixture')
                assert runtime.commands[-1] == 'note fixture'
                await expect(reply).to_have_text('FRIDAY handled: note fixture')
                await expect(reply).to_be_visible()
                await expect(page.locator('.expanded-body')).to_be_hidden()
                await page.mouse.move(0, 700)
                await page.wait_for_timeout(300)
                orb = await page.locator('.character').bounding_box()
                capsule_bounds = await surface.bounding_box()
                await page.screenshot(path=str(ROOT / 'tasks/island-integration/capsule-reply.png'))
                assert abs(orb['x'] - capsule_bounds['x'] - 16) < 2, f'Mochi did not move to the left edge: {orb}, {capsule_bounds}'
                await page.clock.fast_forward(6000)
                await expect(reply).to_be_hidden()
                await summon()
                await expect(page.locator('.friday-transcript')).to_contain_text('FRIDAY handled: note fixture')
                await submit('next')
                await expect(reply).to_contain_text('Fixture class')
                assert 'next' not in runtime.commands
                await submit('open my college schedules')
                await expect(reply).to_have_text('FRIDAY handled: open my college schedules')
                await submit('ask fixture')
                await expect(page.locator('.capsule-reply-pending')).to_be_visible()
                runtime.event('notification', 'Fixture reminder')
                await asyncio.sleep(1.2)
                await expect(reply).to_have_text('FRIDAY handled: ask fixture')
                await page.clock.fast_forward(31000)
                await expect(page.locator('.capsule-reply-pending')).to_be_visible()
                runtime.event('reply_state', '')
                runtime.events[-1]['awaiting_reply'] = False
                await expect(reply).to_have_text('Fixture reminder')
                await page.mouse.move(0, 700)
                await page.clock.fast_forward(20000)
                await expect(reply).to_be_visible()
                await page.clock.fast_forward(11000)
                await expect(reply).to_be_hidden()
                await submit('work fixture')
                await expect(reply).to_have_text('Report saved.')
                await page.mouse.move(0, 700)
                await page.clock.fast_forward(6000)
                await expect(reply).to_be_visible()
                await acknowledge()
                await expect(reply).to_be_hidden()
                await submit('long fixture')
                await expect(reply).to_contain_text('27. Detailed result')
                assert await reply.evaluate('node=>node.scrollHeight>node.clientHeight'), 'Long reply is not scrollable'
                await page.mouse.move(0, 700)
                await page.wait_for_timeout(300)
                await page.screenshot(path=str(ROOT / 'tasks/island-integration/capsule-long-reply.png'))
                await page.clock.fast_forward(20000)
                await expect(reply).to_be_visible()
                await page.clock.fast_forward(11000)
                await expect(reply).to_be_hidden()
                runtime.event('response', 'Opened Calculator')
                runtime.events[-1]['transient'] = True
                await expect(reply).to_have_text('Opened Calculator')
                await page.evaluate("window.dispatchEvent(new Event('blur'))")
                await expect(reply).to_be_visible()
                await acknowledge()
                runtime.event('notification', 'Reminder A')
                runtime.events[-1]['buttons'] = [['Done', 'friday://reply?token=fixture&answer=done']]
                await expect(reply).to_have_text('Reminder A')
                runtime.event('notification', 'Reminder B')
                await asyncio.sleep(1.2)
                await page.locator('.capsule-reply-actions').get_by_role('button', name='Done', exact=True).click()
                await acknowledge()
                await expect(reply).to_have_text('Reminder B')
                runtime.action_release.set()
                await asyncio.sleep(.4)
                await expect(reply).to_have_text('Reminder B')
                await acknowledge()
                await expect(reply).to_have_text('Requested')
                await acknowledge()
                await page.evaluate("window.__emit('hotkey','expand')")
                await command.fill('Keep this command draft')
                runtime.event('notification', 'Queued while typing')
                await asyncio.sleep(1.2)
                await page.clock.fast_forward(31000)
                await expect(command).to_have_value('Keep this command draft')
                await expect(reply).to_be_hidden()
                await command.press('Escape')
                await expect(reply).to_have_text('Queued while typing')
                await acknowledge()
                runtime.event('response', 'Brief voice reply')
                runtime.events[-1]['transient'] = True
                await expect(reply).to_have_text('Brief voice reply')
                await reply.hover()
                await page.clock.fast_forward(6000)
                await expect(reply).to_be_visible()
                await page.mouse.move(0, 700)
                await page.clock.fast_forward(6000)
                await expect(reply).to_be_hidden()
                runtime.automation = {'job_id': 'fixture-job', 'active': True, 'state': 'running', 'response': 'Working'}
                await asyncio.sleep(1.2)
                runtime.automation = {'job_id': 'fixture-job', 'active': False, 'state': 'completed', 'response': 'Research result'}
                await expect(reply).to_have_text('Research result')
                await acknowledge()
                await asyncio.sleep(1.2)
                await expect(reply).to_be_hidden()
                await submit('private fixture')
                await expect(reply).to_have_text('Fixture private response')
                await page.evaluate("window.dispatchEvent(new Event('blur'))")
                await expect(reply).to_have_text('')
                assert 'Fixture private response' not in await page.locator('body').text_content()
                await summon()
                await expect(page.locator('.friday-transcript')).not_to_contain_text('private fixture')
                await expect(page.locator('.friday-transcript')).not_to_contain_text('Opened Calculator')
                assert await page.locator('.friday-turn.assistant').count() <= 3
                assert await page.locator('.friday-turn').count() <= 6
                assert await page.evaluate('localStorage.length') == 0
                # Slow replies remain visible through idle, old reply expiry and voice state updates.
                for idle in ['always', 'hover', 'auto-hide']:
                    await page.get_by_role('button', name='Settings', exact=True).first.click()
                    await page.get_by_label('When idle').select_option(idle)
                    await page.keyboard.press('Escape')
                    if not await command.is_visible(): await page.evaluate("window.__emit('hotkey','expand')")
                    runtime.release = asyncio.Event()
                    await command.fill('slow')
                    await page.evaluate('window.nativeModes=[];window.regionWidths=[]')
                    await command.press('Enter')
                    await expect(reply).to_have_text('Working…')
                    await expect(reply).to_be_visible()
                    runtime.automation = {'job_id': 'background-' + idle, 'active': False,
                                          'state': 'completed', 'response': 'Background result ' + idle}
                    runtime.event('reply_state', '')
                    runtime.events[-1]['awaiting_reply'] = False
                    await asyncio.sleep(1.2)
                    await page.mouse.move(0, 700)
                    await page.clock.fast_forward(35000)
                    await expect(reply).to_have_text('Working…')
                    await expect(reply).to_be_visible()
                    assert 'hidden' not in await page.evaluate('window.nativeModes'), idle
                    assert all(width > 1 for width in await page.evaluate('window.regionWidths')), idle
                    runtime.release.set()
                    await expect(page.locator('input.command')).to_be_enabled()
                    await expect(reply).to_have_text('FRIDAY handled: slow')
                    assert 'hidden' not in await page.evaluate('window.nativeModes'), idle
                    await acknowledge()
                    await expect(reply).to_have_text('Background result ' + idle)
                    await acknowledge()
                    await summon()
                await page.get_by_role('button', name='Settings', exact=True).first.click()
                await page.get_by_label('When idle').select_option('always')
                await page.keyboard.press('Escape')
                await page.evaluate("window.__emit('hotkey','expand')")
                await page.get_by_role('button', name='Projects', exact=True).first.click()
                await page.get_by_role('button', name='Plugins', exact=True).click()
                college_widget = page.locator('[data-plugin="college_schedule"]')
                await expect(college_widget).to_contain_text('Fixture class')
                next_class.update(subject='Next real fixture class', start='14:00')
                await expect(college_widget).to_contain_text('Next real fixture class', timeout=7000)
                await page.keyboard.press('Escape')
                await expect(page.locator('.capsule-schedule')).to_contain_text('Next real fixture class')
                await summon()
                await page.evaluate("window.dispatchEvent(new Event('blur'))")
                await page.wait_for_function('window.targetClears > 0')
                await page.get_by_role('button', name='Listen', exact=True).click()
                await summon()
                await expect(page.locator('.friday-status')).to_have_text('Listening')
                await page.get_by_role('button', name='Stop listening', exact=True).click()
                await expect(page.locator('.friday-status')).to_have_text('FRIDAY ready')
                await page.get_by_role('button', name='Settings', exact=True).first.click()
                color = page.get_by_label('Character glow')
                # Focused settings drafts survive incoming questions.
                await color.focus()
                runtime.event('question', 'Fixture question')
                await asyncio.sleep(1.2)
                await expect(color).to_be_visible()
                assert await color.evaluate('(node)=>document.activeElement===node')
                await page.get_by_label('When idle').select_option('hover')
                await page.keyboard.press('Escape')
                await expect(reply).to_have_text('Fixture question')
                await expect(reply).to_be_visible()
                await acknowledge()
                await expect(surface).to_have_attribute('data-mode', 'hidden')
                runtime.event('notification', 'Hidden reminder')
                await expect(reply).to_have_text('Hidden reminder')
                await expect(reply).to_be_visible()
                assert await page.evaluate('document.hasFocus()'), 'Passive reminder changed browser focus state'
                await acknowledge()
                await expect(surface).to_have_attribute('data-mode', 'hidden')
                await page.evaluate("window.__emit('hotkey','expand')")
                await page.get_by_role('button', name='Settings', exact=True).first.click()
                await page.get_by_label('When idle').select_option('always')
                await page.get_by_role('button', name='FRIDAY', exact=True).first.click()
                await page.screenshot(path=str(ROOT / 'tasks/island-integration/merged-ui.png'))
                # Sneak remains enabled across responses, dismissals, passive events and reload.
                surface = page.locator('.surface')
                await page.evaluate("window.__emit('hotkey','sneak')")
                await expect(surface).to_have_attribute('data-mode', 'sneak')
                await submit('ask fixture')
                await expect(surface).to_have_attribute('data-mode', 'sneak')
                await expect(page.locator('.sneak-reply')).to_contain_text('FRIDAY handled: ask fixture')
                await expect(page.locator('.character')).to_be_hidden()
                await expect(page.locator('.expanded-body')).to_be_hidden()
                await command.press('Escape')
                await expect(surface).to_have_attribute('data-mode', 'hidden')
                runtime.event('question', 'Sneak question must stay hidden')
                await page.evaluate("window.__emit('pointer',{x:360,y:0,reveal:true})")
                await asyncio.sleep(1.2)
                await expect(surface).to_have_attribute('data-mode', 'hidden')
                await page.reload()
                await page.wait_for_function("document.querySelector('.surface')?.classList.contains('offline')===false")
                await expect(surface).to_have_attribute('data-mode', 'hidden')
                await page.evaluate("window.__emit('hotkey','expand')")
                await expect(surface).to_have_attribute('data-mode', 'sneak')
                runtime.release = asyncio.Event()
                await command.fill('slow'); await command.press('Enter')
                await expect(surface).to_have_attribute('data-mode', 'hidden')
                await page.evaluate("window.__emit('hotkey','expand')")
                await command.press('Escape')
                runtime.release.set()
                await expect(page.locator('input.command')).to_be_enabled()
                await expect(surface).to_have_attribute('data-mode', 'hidden')
                await page.evaluate("window.__emit('hotkey','expand')")
                await submit('private fixture')
                await expect(page.locator('.sneak-reply')).to_contain_text('Fixture private response')
                await page.evaluate("window.dispatchEvent(new Event('blur'))")
                await expect(surface).to_have_attribute('data-mode', 'hidden')
                await expect(page.locator('.sneak-reply')).to_have_text('')
                assert 'Fixture private response' not in await page.locator('body').text_content()
                await page.evaluate("window.__emit('hotkey','sneak')")
                await summon()
                for ws in tuple(bridge.clients): await ws.close()
                await expect(page.locator('.friday-status')).to_have_text('FRIDAY disconnected')
                await page.get_by_role('button', name='Start FRIDAY', exact=True).click()
                assert await page.evaluate('window.starts') == 1
                assert not errors, errors
                await browser.close()
                print('PASS: authenticated merged UI, real plugin aliases, command fallback, transcript, private cleanup, pending replies, voice state/stop, draft preservation and offline Start')


if __name__ == '__main__': asyncio.run(main())
