"""Chromium UI/SSE ordering check with fake IPC/data; no owner state is used.

Start Vite, then run: venv/Scripts/python.exe -B tests/island/check_briefings_browser.py
"""
import asyncio
import json
from pathlib import Path
import sys

from playwright.async_api import async_playwright, expect
from websockets.asyncio.server import serve

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.friday_island_server.config import IslandConfig

TOKEN = 'c' * 64  # Synthetic fixture token.
BODY = 'Good morning.\nFirst: Physics at 10:00 with Prof. Ray.\nLab report due tomorrow.\n2 open todos.\nYesterday: 45 focus minutes.\nBattery 39%.'
SCRIPT = r"""
window.isTauri = true;
window.fixture = CONFIG;
window.modes = []; window.actionBodies = []; window.eventToken = '';
const callbacks = new Map(), listeners = new Map(); let sequence = 0;
window.__emit = (name, payload) => listeners.get(name)?.({payload});
window.__TAURI_INTERNALS__ = {
  transformCallback(fn) { const id=++sequence; callbacks.set(id,fn); return id; },
  async invoke(cmd,args={}) {
    if (cmd==='get_config' || cmd==='reload_config') return structuredClone(window.fixture);
    if (cmd==='runtime_status') return {mode:'rest',hotkey_errors:[],max_width:720,max_height:560,reduce_motion:true,fullscreen_front:false};
    if (cmd==='startup_status') return {phase:'external',error:'',owned_pid:null,attempts:0,isolated:false,login_enabled:false};
    if (cmd==='desktop_status') return {battery:null,media:null};
    if (cmd==='app_index_status') return {count:0,scanning:false,updated_at:0,errors:[]};
    if (cmd==='search_apps') return [];
    if (cmd==='set_mode') { window.modes.push(args.mode); return; }
    if (cmd==='plugin:event|listen') { listeners.set(args.event,callbacks.get(args.handler)); return ++sequence; }
    return null;
  }
};
const originalFetch = window.fetch.bind(window);
window.fetch = async (url, options={}) => {
  if (!String(url).includes('/api/')) return originalFetch(url,options);
  if (String(url).endsWith('/api/events')) {
    window.eventToken = new Headers(options.headers).get('X-Friday-Token');
    return new Response(new ReadableStream({start(controller) {
      window.__pluginEvent = event => controller.enqueue(new TextEncoder().encode('data: '+JSON.stringify(event)+'\n\n'));
    }}), {headers:{'Content-Type':'text/event-stream'}});
  }
  if (String(url).includes('/briefings/actions/')) {
    window.actionBodies.push(JSON.parse(options.body));
    return new Response(JSON.stringify({ok:true,text:'Brief snoozed for 30 minutes.'}),{status:200});
  }
  return new Response('{}',{status:404});
};
"""


async def main():
    cases, current = [], {}
    async def handle(ws):
        hello = json.loads(await ws.recv())
        assert hello['token'] == TOKEN
        async def send(kind, **value):
            await ws.send(json.dumps(dict(v=1, type=kind, **value)))
        await send('handshake', id=hello['id'], ok=True)
        await send('status', integrated=current['integrated'], plugin_api_port=19999)
        await send('plugin_list', plugins=[])
        async for raw in ws:
            request = json.loads(raw)
            if request['type'] != 'command':
                await send(request['type'], id=request['id'], items=[], widget={'title': 'Fixture', 'text': ''})
                continue
            card = dict(topic='ui.card', plugin_id='briefings', payload=dict(title='Morning brief', body=BODY,
                ttl_s=600, card_id='a'*32, actions=[dict(id='snooze', label='Snooze 30 min', payload={'card_id': 'a'*32})]))
            async def publish():
                await current['page'].evaluate('event => window.__pluginEvent(event)', card)
            if current['card_first']:
                await publish()
                await asyncio.sleep(.15)
            await send('command_result', id=request['id'], ok=True, text=BODY, private=True, model='briefings')
            if not current['card_first']:
                await asyncio.sleep(.15)
                await publish()
    async with serve(handle, '127.0.0.1', 0) as server, async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            for integrated in [False, True]:
                for card_first in [True, False]:
                    current.update(integrated=integrated, card_first=card_first)
                    config = IslandConfig().model_dump()
                    config['connection'].update(port=server.sockets[0].getsockname()[1], api_port=19999, token=TOKEN)
                    config['island'].update(boot_animation=False, reduced_motion=True)
                    page = await browser.new_page(viewport={'width': 720, 'height': 560}, reduced_motion='reduce')
                    current['page'] = page
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    await page.add_init_script(SCRIPT.replace('CONFIG', json.dumps(config)))
                    await page.goto('http://127.0.0.1:1420')
                    await page.wait_for_function('Boolean(window.__pluginEvent)')
                    await page.evaluate("window.__emit('hotkey','expand')")
                    command = page.get_by_role('combobox', name='FRIDAY command')
                    await expect(command).to_be_visible()
                    await command.fill('brief me')
                    await command.press('Enter')
                    card = page.locator('[data-plugin="briefings"]')
                    await expect(card).to_be_visible()
                    await expect(card.locator('p')).to_have_text(BODY)
                    await expect(command).to_be_enabled()
                    await expect(page.locator('.surface')).to_have_attribute('data-mode', 'expanded')
                    await expect(page.locator('.friday-turn.private')).to_have_count(0)
                    assert await page.evaluate('window.eventToken') == TOKEN
                    assert await page.locator('.surface').evaluate('node => Math.round(node.getBoundingClientRect().width)') == 640
                    output = ROOT / 'tasks/schedule-briefings/browser.png'
                    output.parent.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(output))
                    await card.get_by_role('button', name='Snooze 30 min', exact=True).click()
                    await expect(card).to_have_count(0)
                    assert await page.evaluate('window.actionBodies') == [{'card_id': 'a'*32}]
                    assert not errors, errors
                    cases.append(dict(integrated=integrated, card_before_result=card_first, passed=True))
                    await page.close()
        finally:
            await browser.close()
    print(json.dumps(dict(cases=cases, authenticated_sse=True, scoped_action=True)))


if __name__ == '__main__':
    asyncio.run(main())
