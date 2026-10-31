"""Real Chromium + real bridge; native IPC is mocked so no owner apps/data change.

Run from the repository with Vite listening on 127.0.0.1:1420:
  venv/Scripts/python.exe -B tests/island/check_browser.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from playwright.async_api import async_playwright, expect
from websockets.asyncio.server import serve

from services.friday_island_server.config import load_config
from services.friday_island_server.engine import Engine
from services.friday_island_server.plugins import CollegePlugin, Registry
from services.friday_island_server.server import Bridge, ORIGINS


async def main():
    async def assistant(text):
        return "A calm, tool-free reply."

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.json"
        config = load_config(path)
        from datetime import datetime
        registry = Registry([CollegePlugin(lambda: {"subject": "DBMS", "start": "10:30"}, now=lambda: datetime(2026, 10, 31, 10, 20))])
        class DelayedBridge(Bridge):
            slow = False
            async def send(self, ws, kind, id=None, **data):
                if kind == 'suggestions' and self.slow:
                    await asyncio.sleep(1.5)
                await super().send(ws, kind, id, **data)

        bridge = DelayedBridge(path, registry, Engine(registry, assistant))
        async with serve(bridge.handle, "127.0.0.1", 0, origins=ORIGINS) as server:
            sample = config.model_dump()
            sample["connection"]["port"] = server.sockets[0].getsockname()[1]
            sample["pins"] = [{"id": str(i), "name": name, "path": "C:/Windows/notepad.exe", "visible": True}
                              for i, name in enumerate(["Notes", "Editor", "Browser"])]
            sample["projects"] = [{"id": "friday", "name": "FRIDAY", "path": "C:/FRIDAY", "color": "#FFB347",
                                   "last_opened": None, "actions": [{"kind": "folder"}]}]
            # The bridge sees the same configured entries as the frontend.
            server_config = dict(sample)
            path.write_text(json.dumps(server_config), encoding="utf-8")
            script = """
                globalThis.isTauri = true;
                window.fixture = SAMPLE;
                window.launches = [];
                window.nativeModes = [];
                window.rescans = 0;
                window.catalog = [
                    {id:'app-'+ 'a'.repeat(32),name:'Calculator',source:'Windows Store',kind:'app',pinned:false},
                    {id:'app-'+ 'b'.repeat(32),name:'Duplicate',source:'Start Menu',kind:'app',pinned:false},
                    {id:'app-'+ 'c'.repeat(32),name:'Duplicate',source:'App Paths',kind:'app',pinned:false},
                    {id:'app-'+ 'd'.repeat(32),name:'Focus',source:'Start Menu',kind:'app',pinned:false}
                ];
                const callbacks = new Map(), listeners = new Map();
                let next = 0;
                window.__emit = (name, payload) => listeners.get(name)?.({payload});
                window.__TAURI_INTERNALS__ = {
                    transformCallback(fn) { const id = ++next; callbacks.set(id, fn); return id; },
                    async invoke(cmd, args) {
                        if (cmd === 'get_config') return structuredClone(window.fixture);
                        if (cmd === 'app_index_status') return {count:window.catalog.length,scanning:false,updated_at:1,errors:[]};
                        if (cmd === 'search_apps') return window.catalog.filter(a=>a.name.toLowerCase().includes(args.query.toLowerCase())).map(a=>({...a,pinned:window.fixture.pins.some(p=>p.app_id===a.id)}));
                        if (cmd === 'rescan_apps') { window.rescans++; return {count:window.catalog.length,scanning:false,updated_at:1,errors:[]}; }
                        if (cmd === 'app_icon') throw new Error('Use glyph in fixture');
                        if (cmd === 'toggle_app_pin') {
                            const index = window.fixture.pins.findIndex(p=>p.app_id===args.id);
                            if (index>=0) window.fixture.pins.splice(index,1);
                            else { const app=window.catalog.find(a=>a.id===args.id); window.fixture.pins.push({id:app.id,app_id:app.id,name:app.name,path:'',visible:true}); }
                            window.fixture.revision++; return structuredClone(window.fixture);
                        }
                        if (cmd === 'save_config') { window.fixture = structuredClone(args.next); window.fixture.revision++; return structuredClone(window.fixture); }
                        if (cmd === 'runtime_status') return {mode:'rest',hotkey_errors:[],acrylic:false,reduce_motion:false};
                        if (cmd === 'set_mode') { window.nativeModes.push(args); return; }
                        if (cmd === 'set_regions') { window.regions = args.rects; return; }
                        if (cmd === 'plugin:event|listen') { listeners.set(args.event, callbacks.get(args.handler)); return ++next; }
                        if (cmd === 'plugin:event|unlisten') return;
                        if (cmd === 'launch') { window.launches.push(args); return 'Opened configured item'; }
                        if (cmd === 'pin_icon') throw new Error('Use original fallback glyph');
                        if (cmd === 'choose_path') return args.folder ? {name:'Workspace',path:'C:/Workspace'} : {name:'New app',path:'C:/Windows/notepad.exe'};
                        if (cmd === 'local_command') {
                            if (args.text.startsWith('open ')) {
                                const query=args.text.slice(5).toLowerCase(),app=window.catalog.find(a=>a.name.toLowerCase().includes(query));
                                return app ? {ok:true,text:'Opening '+app.name,action:{kind:'app',id:app.id}} : {ok:false,text:'No app found. Rescan apps in Settings.'};
                            }
                            return {ok:true,text:'Settings',action:{kind:'settings'}};
                        }
                        throw new Error('Unexpected native call: ' + cmd);
                    }
                };
            """.replace("SAMPLE", json.dumps(sample))
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                page = await browser.new_page(viewport={"width": 720, "height": 560}, device_scale_factor=1.5)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.add_init_script(script)
                await page.goto("http://127.0.0.1:1420")
                surface = page.locator(".surface")
                await expect(page.locator(".live-line")).to_have_text("Next: DBMS · 10:30")
                for ws in tuple(bridge.clients):
                    await bridge.send(ws, 'pill_snippet_update', text='', plugin=None)
                await expect(page.locator('#app')).to_have_class('character-only')
                for ws in tuple(bridge.clients):
                    await bridge.send(ws, 'pill_snippet_update', text='Next: DBMS · 10:30', plugin='college_schedule')
                await expect(page.locator('#app')).not_to_have_class('character-only')
                await expect(surface).to_have_attribute("data-mode", "rest")
                await surface.hover()
                await expect(surface).to_have_attribute("data-mode", "peek")
                assert not any(v["activate"] for v in await page.evaluate("window.nativeModes"))
                await page.evaluate("window.__emit('hotkey','expand')")
                await expect(surface).to_have_attribute("data-mode", "expanded")
                await page.screenshot(path="tasks/island-expanded.png")
                await page.get_by_role("button", name="Plugins", exact=True).click()
                await expect(page.locator(".widget")).to_contain_text("DBMS")
                await page.get_by_role("button", name="Settings", exact=True).last.click()
                await page.get_by_role("button", name="Pinned apps", exact=True).click()
                await page.get_by_role("button", name="Add app", exact=True).click()
                await expect(page.get_by_role("textbox", name="New app display name")).to_be_visible()
                await page.get_by_role("button", name="Move New app up", exact=True).click()
                assert (await page.evaluate("window.fixture.pins.map(p=>p.name)"))[2] == "New app"
                await page.locator('.config-row').first.drag_to(page.locator('.config-row').last)
                assert (await page.evaluate("window.fixture.pins.map(p=>p.name)"))[-1] == 'Notes'
                await page.get_by_role('button', name='Remove New app', exact=True).click()
                await page.get_by_role('button', name='Remove New app', exact=True).click()
                assert len(await page.evaluate('window.fixture.pins')) == 3
                await page.get_by_role('button', name='Pin Calculator', exact=True).click()
                await expect(page.get_by_role('textbox', name='Calculator display name')).to_be_visible()
                await page.get_by_role('button', name='Unpin Calculator', exact=True).click()
                await expect(page.get_by_role('textbox', name='Calculator display name')).to_have_count(0)
                editor = page.get_by_role('textbox', name='Editor display name')
                await editor.fill('Editor renamed'); await editor.press('Tab')
                assert any(p['name']=='Editor renamed' for p in await page.evaluate('window.fixture.pins'))
                assert any(p['name']=='Browser' for p in await page.evaluate('window.fixture.pins'))
                await page.get_by_role("button", name="Projects", exact=True).last.click()
                await page.get_by_role("button", name="Add project", exact=True).click()
                await page.get_by_role("button", name="Save project", exact=True).click()
                assert len(await page.evaluate("window.fixture.projects")) == 2
                await page.get_by_role('button', name='Move Workspace up', exact=True).click()
                assert (await page.evaluate('window.fixture.projects'))[0]['name'] == 'Workspace'
                await page.keyboard.press("Escape")
                await expect(surface).to_have_attribute("data-mode", "rest")
                await page.evaluate("window.__emit('hotkey','sneak')")
                await expect(surface).to_have_attribute("data-mode", "sneak")
                await expect(surface).to_have_attribute('data-mood', 'sleepy')
                command = page.get_by_role("combobox", name="FRIDAY command")
                await command.fill("ne")
                await expect(page.get_by_role("option").first).to_contain_text("next")
                await command.press("ArrowDown")
                await command.press("Tab")
                await expect(command).to_have_value("next")
                await page.screenshot(path="tasks/island-sneak.png")
                await command.press("Enter")
                await expect(surface).to_have_attribute("data-mode", "rest")
                await expect(page.locator(".feedback")).to_contain_text("DBMS")
                await page.evaluate("window.__emit('hotkey','sneak')")
                await command.fill('open dupl')
                await expect(page.get_by_role('option')).to_have_count(2)
                await command.press('ArrowDown'); await command.press('ArrowDown'); await command.press('Tab'); await command.press('Enter')
                await expect(surface).to_have_attribute('data-mode','rest')
                assert (await page.evaluate('window.launches'))[-1] == {'kind':'app','id':'app-'+'c'*32}, 'Tab lost selected app ID'
                await page.evaluate("window.__emit('hotkey','sneak')")
                await command.fill('focus'); await command.press('Enter')
                await expect(page.locator('.feedback')).to_contain_text('tool-free reply')
                assert len(await page.evaluate('window.launches')) == 1, 'App name stole plugin command'
                bridge.slow = True
                await page.evaluate("window.__emit('hotkey','sneak')")
                await command.fill('calc')
                await expect(page.get_by_role('option').first).to_contain_text('Calculator', timeout=900)
                bridge.slow = False
                await command.press('Escape')
                # Offline mode must recover the same UI without a backend.
                server.close()
                await server.wait_closed()
                await expect(page.locator(".live-line")).to_have_text("FRIDAY offline")
                await page.evaluate("window.__emit('hotkey','sneak')")
                await command.fill('calc')
                await expect(page.get_by_role('option').first).to_contain_text('Calculator')
                await page.get_by_role('button', name='Pin Calculator', exact=True).click()
                assert any(p.get('app_id')=='app-'+'a'*32 for p in await page.evaluate('window.fixture.pins'))
                await command.press('ArrowDown'); await command.press('Enter')
                await expect(surface).to_have_attribute('data-mode','rest')
                assert (await page.evaluate('window.launches'))[-1]['id'] == 'app-'+'a'*32
                await page.evaluate("window.__emit('hotkey','sneak')")
                await command.fill('open app-does-not-exist')
                await expect(page.get_by_role('option')).to_contain_text('No app found')
                await command.press('ArrowDown'); await command.press('Enter')
                assert await page.evaluate('window.rescans') == 1
                await command.press('Escape')
                await page.evaluate("window.__emit('hotkey','sneak')")
                await command.fill("settings")
                await command.press("Enter")
                await expect(surface).to_have_attribute("data-mode", "expanded")
                async with serve(bridge.handle, '127.0.0.1', sample['connection']['port'], origins=ORIGINS):
                    await expect(page.locator('.live-line')).to_have_text('Next: DBMS · 10:30', timeout=10000)
                await page.emulate_media(reduced_motion="reduce")
                assert await page.locator(".character > svg").evaluate("node => getComputedStyle(node).animationName") == "none"
                assert not errors, errors
                assert await page.evaluate("window.launches.length") == 2
                await browser.close()
                print("PASS: real bridge/Chromium, four states, app ID selection + Tab, pin/unpin, reorder, command priority, offline app search/launch, rescan, reconnect, reduced motion")


if __name__ == "__main__":
    asyncio.run(main())
