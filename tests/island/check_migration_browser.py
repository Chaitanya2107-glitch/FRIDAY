"""Chromium migration checks using synthetic services and native IPC only."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from playwright.async_api import async_playwright, expect
from websockets.asyncio.server import serve

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.friday_island_server.config import load_config
from services.friday_island_server.server import Bridge, ORIGINS
from services.mind.cognition import cognition
from check_briefings_browser import SCRIPT
from check_friday import Runtime


class Tools:
    def __init__(self):
        self.calls, self.private_pending = [], set()
    async def suggestions(self, owner):
        return [{'text': 'list reminders', 'detail': 'Suggested for you', 'fill': True}]
    async def outcome(self, owner, sent=None): pass
    def disconnect(self, owner): pass
    async def request(self, owner, action, item='', value=''):
        self.calls.append((action, item, value))
        if action == 'features':
            from dataclasses import asdict
            from interfaces.control_center.catalog import CAPABILITIES
            return {'items': [asdict(row) for row in CAPABILITIES]}
        if action == 'plugins':
            return {'items': [dict(id='focus', name='Focus', status='loaded', enabled=True,
                                   description='Offline timer', commands=[{'help': 'Focus timer', 'examples': ['focus 25']}]) ]}
        if action == 'read':
            return {'clipboard': [{'id': 'fixture', 'text': '<img src=x onerror=alert(1)> private clipboard'}],
                    'files': {'enabled': True, 'files': 3, 'folders': ['C:/fixture']},
                    'stats': ['CPU 1%'], 'routines': ['work routine']}
        if action == 'files_search': return {'results': [{'id': 'file-fixture', 'name': 'Fixture.txt', 'path': 'C:/fixture/Fixture.txt'}]}
        return {'ok': True, 'text': 'Fixture action completed'}


class MigrationRuntime(Runtime):
    suppressed = False
    local_pending = False
    async def action(self, action, value=''):
        if action == 'local_ready': return {'ok': True, 'pending': self.local_pending}
        return await super().action(action, value)
    async def snapshot(self, since):
        return {**await super().snapshot(since), 'display_suppressed': self.suppressed}
    async def command(self, text, owner, target):
        if text.startswith('\\c'):
            self.commands.append(text)
            return {'ok': True, 'private': True, 'model': 'computer_agent',
                    'text': 'Private proposed step' if text != '\\c yes' else 'Private step completed',
                    'awaiting_reply': text != '\\c yes'}
        return await super().command(text, owner, target)


async def main():
    with tempfile.TemporaryDirectory() as directory, patch.object(cognition, 'path', Path(directory) / 'mind.db'):
        config_path = Path(directory) / 'config.json'
        config = load_config(config_path)
        runtime = MigrationRuntime()
        bridge = Bridge(config_path, runtime=runtime)
        bridge.tools = Tools()
        async with serve(bridge.handle, '127.0.0.1', 0, origins=ORIGINS) as server, async_playwright() as playwright:
            sample = config.model_dump()
            sample['connection']['port'] = server.sockets[0].getsockname()[1]
            sample['island']['boot_animation'] = False
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={'width': 800, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.add_init_script(SCRIPT.replace('CONFIG', json.dumps(sample)))
            print('Starting Chromium migration fixture', flush=True)
            await page.goto('http://127.0.0.1:1420')
            await expect(page.locator('.friday-status')).to_have_count(0)
            await page.wait_for_function("!document.querySelector('.surface').classList.contains('offline')")
            await page.evaluate("window.__emit('hotkey','expand')")
            await page.get_by_role('button', name='FRIDAY', exact=True).first.click()
            await expect(page.locator('.friday-status')).to_have_text('FRIDAY ready')
            print('Island connected', flush=True)
            for label in ['Talk on her own', 'Stop microphone', 'Remote off', 'Control Center & Guide', 'Clear saved chat memory']:
                await expect(page.get_by_role('button', name=label, exact=True)).to_be_visible()
            await expect(page.get_by_role('button', name='All controls', exact=True)).to_have_count(0)
            await expect(page.get_by_role('button', name='Show / hide robot', exact=True)).to_have_count(0)
            await page.get_by_role('button', name='Desktop tools', exact=True).click()
            await expect(page.locator('.clipboard-entry p')).to_contain_text('<img src=x')
            assert await page.locator('.clipboard-entry img').count() == 0
            await page.get_by_role('button', name='Copy', exact=True).click()
            await page.get_by_label('Search indexed files').fill('Fixture')
            await page.get_by_role('button', name='Search', exact=True).click()
            await expect(page.locator('.file-result')).to_contain_text('Fixture.txt')
            await page.get_by_role('button', name='Open file', exact=True).click()
            await page.get_by_role('button', name='Show in folder', exact=True).click()
            await page.get_by_role('button', name='Rescan files', exact=True).click()
            await asyncio.sleep(.1)
            assert any(row[0] == 'clipboard_copy' and row[1] == 'fixture' for row in bridge.tools.calls)
            assert any(row[0] == 'files_rescan' for row in bridge.tools.calls)
            assert any(row[0] == 'files_open' for row in bridge.tools.calls)
            print('Private desktop tools passed', flush=True)
            await page.get_by_role('button', name='Features', exact=True).click()
            await expect(page.locator('[data-feature]')).to_have_count(67)
            await page.get_by_label('Search FRIDAY features').fill('care')
            care = page.locator('[data-feature="care"]'); await care.locator('summary').click()
            before = list(runtime.commands)
            await care.get_by_role('button', name='care status', exact=True).click()
            await expect(page.get_by_role('combobox', name='FRIDAY command')).to_have_value('care status')
            assert runtime.commands == before
            await page.get_by_role('button', name='Plugins', exact=True).click()
            await expect(page.get_by_role('button', name='Disable Focus', exact=True)).to_be_visible()
            await page.get_by_role('button', name='focus 25', exact=True).click()
            await expect(page.get_by_role('combobox', name='FRIDAY command')).to_have_value('focus 25')
            await page.get_by_role('button', name='Settings', exact=True).first.click()
            await expect(page.locator('.clipboard-entry')).to_have_count(0)
            command = page.get_by_role('combobox', name='FRIDAY command')
            runtime.local_pending = True
            await command.fill('/open Calculator'); await command.press('Enter')
            await expect(page.locator('.capsule-reply-text')).to_have_text('FRIDAY handled: \\o Calculator')
            assert runtime.commands[-1] == '\\o Calculator'
            runtime.local_pending = False
            await page.evaluate("window.__emit('hotkey','expand')")
            await command.fill('open phone link'); await command.press('Enter')
            await expect(page.locator('.capsule-reply-text')).to_have_text('FRIDAY handled: open phone link')
            await page.evaluate("window.__emit('hotkey','expand')")
            await command.fill('\\c fixture task')
            await command.press('Enter')
            await expect(page.locator('.friday-turn.private')).to_contain_text('Private proposed step')
            await page.get_by_role('button', name='Approve this step', exact=True).click()
            await expect(page.locator('.friday-turn.private')).to_contain_text('Private step completed')
            assert runtime.commands[-1] == '\\c yes'
            print('Computer approvals passed', flush=True)
            runtime.suppressed = True
            await expect(page.locator('.surface')).to_have_attribute('data-mode', 'hidden')
            await expect(page.locator('.surface')).to_be_hidden()
            await page.evaluate("window.__emit('hotkey','expand'); window.__emit('hotkey','sneak'); window.__emit('pointer',{x:400,y:0,reveal:true})")
            runtime.event('notification', 'Must not cover a game')
            await page.wait_for_timeout(1300)
            await expect(page.locator('.surface')).to_be_hidden()
            runtime.suppressed = False
            await expect(page.locator('.surface')).to_have_attribute('data-mode', 'rest')
            await expect(page.locator('.surface')).to_be_visible()
            await expect(page.locator('.friday-turn.private')).to_have_count(0)
            await page.evaluate("window.__emit('native-status',{mode:'hidden',hotkey_errors:[],max_width:720,max_height:560,reduce_motion:true,display_suppressed:true})")
            await expect(page.locator('.surface')).to_be_hidden()
            await page.evaluate("window.__emit('hotkey','expand')")
            await expect(page.locator('.surface')).to_be_hidden()
            await page.evaluate("window.__emit('native-status',{mode:'hidden',hotkey_errors:[],max_width:720,max_height:560,reduce_motion:true,display_suppressed:false})")
            await expect(page.locator('.surface')).to_have_attribute('data-mode', 'rest')
            await page.evaluate("window.__emit('hotkey','expand')")
            await command.fill('')
            await command.dispatch_event('input')
            await expect(page.get_by_role('option').filter(has_text='Suggested for you')).to_be_visible()
            await page.get_by_role('option').filter(has_text='Suggested for you').get_by_role('button').click()
            await expect(command).to_have_value('list reminders')
            assert runtime.commands[-1] == '\\c yes'
            await command.fill('')
            await page.evaluate("window.__emit('hotkey','dictate')")
            await page.wait_for_timeout(100)
            await command.evaluate("node => { node.value = 'note dictated fixture'; node.dispatchEvent(new InputEvent('input', { inputType: 'insertFromPaste', bubbles: true })); }")
            await expect(page.locator('.capsule-reply-text')).to_have_text('FRIDAY handled: note dictated fixture')
            assert runtime.commands[-1] == 'note dictated fixture'
            assert not errors, errors
            output = ROOT / 'tasks/island-parity'
            output.mkdir(exist_ok=True)
            (output / 'browser.json').write_text(json.dumps({'passed': True, 'private_tools': True,
                'computer_approval': True, 'prediction_fill_only': True, 'gaming_blocks_reveal': True,
                'passive_restore': True, 'all_features': 67, 'installed_plugins': True,
                'confirmation_precedence': True, 'phone_link_routing': True, 'handy_auto_submit': True,
                'page_errors': errors}, indent=2), encoding='utf-8')
            await browser.close()
    print('Migration browser checks passed')


if __name__ == '__main__':
    import faulthandler
    faulthandler.dump_traceback_later(60)
    asyncio.run(main())
