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
        registry = Registry([CollegePlugin(lambda: {"subject": "DBMS", "start": "10:30"})])
        bridge = Bridge(path, registry, Engine(registry, assistant))
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
                const callbacks = new Map(), listeners = new Map();
                let next = 0;
                window.__emit = (name, payload) => listeners.get(name)?.({payload});
                window.__TAURI_INTERNALS__ = {
                    transformCallback(fn) { const id = ++next; callbacks.set(id, fn); return id; },
                    async invoke(cmd, args) {
                        if (cmd === 'get_config') return structuredClone(window.fixture);
                        if (cmd === 'save_config') { window.fixture = structuredClone(args.next); window.fixture.revision++; return structuredClone(window.fixture); }
                        if (cmd === 'runtime_status') return {mode:'rest',hotkey_errors:[],acrylic:false,reduce_motion:false};
                        if (cmd === 'set_mode') { window.nativeModes.push(args); return; }
                        if (cmd === 'set_regions') { window.regions = args.rects; return; }
                        if (cmd === 'plugin:event|listen') { listeners.set(args.event, callbacks.get(args.handler)); return ++next; }
                        if (cmd === 'plugin:event|unlisten') return;
                        if (cmd === 'launch') { window.launches.push(args); return 'Opened configured item'; }
                        if (cmd === 'pin_icon') throw new Error('Use original fallback glyph');
                        if (cmd === 'choose_path') return args.folder ? {name:'Workspace',path:'C:/Workspace'} : {name:'New app',path:'C:/Windows/notepad.exe'};
                        if (cmd === 'local_command') return {ok:true,text:'Settings',action:{kind:'settings'}};
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
                await page.get_by_role("button", name="Apps", exact=True).click()
                await page.get_by_role("button", name="Add app", exact=True).click()
                await expect(page.get_by_role("textbox", name="New app display name")).to_be_visible()
                await page.get_by_role("button", name="Move New app up", exact=True).click()
                assert (await page.evaluate("window.fixture.pins.map(p=>p.name)"))[2] == "New app"
                await page.locator('.config-row').first.drag_to(page.locator('.config-row').last)
                assert (await page.evaluate("window.fixture.pins.map(p=>p.name)"))[-1] == 'Notes'
                await page.get_by_role('button', name='Remove New app', exact=True).click()
                await page.get_by_role('button', name='Remove New app', exact=True).click()
                assert len(await page.evaluate('window.fixture.pins')) == 3
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
                # Offline mode must recover the same UI without a backend.
                server.close()
                await server.wait_closed()
                await expect(page.locator(".live-line")).to_have_text("FRIDAY offline")
                await page.evaluate("window.__emit('hotkey','sneak')")
                await command.fill("settings")
                await command.press("Enter")
                await expect(surface).to_have_attribute("data-mode", "expanded")
                async with serve(bridge.handle, '127.0.0.1', sample['connection']['port'], origins=ORIGINS):
                    await expect(page.locator('.live-line')).to_have_text('Next: DBMS · 10:30', timeout=10000)
                await page.emulate_media(reduced_motion="reduce")
                assert await page.locator(".character > svg").evaluate("node => getComputedStyle(node).animationName") == "none"
                assert not errors, errors
                assert not await page.evaluate("window.launches.length")
                await browser.close()
                print("PASS: real bridge/Chromium, four states, passive hover, suggestions + Tab/Enter, plugins, app/project persistence/reorder, offline settings, reconnect, reduced motion")


if __name__ == "__main__":
    asyncio.run(main())
