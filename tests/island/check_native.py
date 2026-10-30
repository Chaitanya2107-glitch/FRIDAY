"""Windows foreground/region smoke check against an isolated debug config.

Requires the Vite server on 127.0.0.1:1420 and cargo build completed. Launches
only the Island and two owned Windows fixtures; does not start FRIDAY or launch pins.
"""
import ctypes as c
import asyncio
import faulthandler
from ctypes import wintypes as w
import json
import hashlib
import zipfile
import os
from pathlib import Path
import subprocess
import sys
import time
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.friday_island_server.config import load_config

u, g = c.windll.user32, c.windll.gdi32
u.SetProcessDpiAwarenessContext.argtypes = [c.c_void_p]
u.SetProcessDpiAwarenessContext(c.c_void_p(-4))
u.GetForegroundWindow.restype = w.HWND
u.GetAncestor.argtypes = [w.HWND, w.UINT]
u.GetAncestor.restype = w.HWND
u.SetForegroundWindow.argtypes = [w.HWND]
u.GetWindowLongPtrW.argtypes = [w.HWND, c.c_int]
u.GetWindowLongPtrW.restype = c.c_ssize_t
u.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.GetWindowRgn.argtypes = [w.HWND, w.HRGN]
g.CreateRectRgn.restype = w.HRGN
g.GetRgnBox.argtypes = [w.HRGN, c.POINTER(w.RECT)]
g.DeleteObject.argtypes = [w.HANDLE]
g.PtInRegion.argtypes = [w.HRGN, c.c_int, c.c_int]
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]
u.CreateWindowExW.restype = w.HWND
u.DestroyWindow.argtypes = [w.HWND]
u.ShowWindow.argtypes = [w.HWND, c.c_int]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
CALLBACK = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [CALLBACK, w.LPARAM]


def main():
    faulthandler.dump_traceback_later(40, repeat=False)
    release = '--release' in sys.argv
    online = '--online' in sys.argv
    label = 'island-native-online' if online else 'island-native-baseline' if '--baseline' in sys.argv else 'island-native-release' if release else 'island-native'
    output = ROOT / "tasks" / label
    output.mkdir(exist_ok=True)
    path = output / "config.json"
    config = load_config(path)
    config.appearance.idle_mode = "always"
    # Defaults can be owned by existing software; use less common test bindings.
    config.hotkeys.sneak = "Ctrl+Shift+Alt+F23"
    config.hotkeys.expand = "Ctrl+Shift+Alt+F24"
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    ready, authenticated, stop = threading.Event(), threading.Event(), threading.Event()
    replies, bridge_errors = [], []
    server_thread = None
    if online:
        from services.friday_island_server.engine import Engine
        from services.friday_island_server.plugins import CollegePlugin, Registry
        from services.friday_island_server.server import Bridge, ORIGINS
        from websockets.asyncio.server import serve

        class ObservedBridge(Bridge):
            async def send(self, ws, kind, id=None, **data):
                if kind == 'handshake' and data.get('ok'): authenticated.set()
                if kind == 'command_result': replies.append(data)
                await super().send(ws, kind, id, **data)

        async def answer(_text): return 'Tool-free fixture reply'

        async def serve_fixture():
            registry = Registry([CollegePlugin(lambda: {'subject': 'DBMS', 'start': '10:30'})])
            bridge = ObservedBridge(path, registry, Engine(registry, answer))
            try:
                async with serve(bridge.handle, '127.0.0.1', 0, origins=ORIGINS) as server:
                    config.connection.port = server.sockets[0].getsockname()[1]
                    path.write_text(config.model_dump_json(indent=2), encoding='utf-8')
                    ready.set()
                    while not stop.is_set(): await asyncio.sleep(.05)
            except Exception as error:
                bridge_errors.append(str(error)); ready.set()

        server_thread = threading.Thread(target=lambda: asyncio.run(serve_fixture()), daemon=True)
        server_thread.start()
        assert ready.wait(5) and not bridge_errors, bridge_errors
    host = u.CreateWindowExW(0, 'STATIC', 'Island test fixture A', 0x10CF0000, 120, 570, 380, 130, None, None, None, None)
    other = u.CreateWindowExW(0, 'STATIC', 'Island test fixture B', 0x10CF0000, 550, 570, 380, 130, None, None, None, None)
    assert host and other, 'Could not create native test windows'

    def pump(seconds=.4):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            message = w.MSG()
            for _ in range(100):
                if not u.PeekMessageW(c.byref(message), None, 0, 0, 1): break
                u.TranslateMessage(c.byref(message)); u.DispatchMessageW(c.byref(message))
            time.sleep(.01)

    def focus(hwnd):
        u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 3)
        u.SetForegroundWindow(hwnd); pump()
        assert u.GetForegroundWindow() == hwnd, "Cannot focus owned test fixture"
        return hwnd

    def key(keys):
        for code in keys: u.keybd_event(code, 0, 0, 0)
        try: pump(.16)
        finally:
            for code in reversed(keys): u.keybd_event(code, 0, 2, 0)
        pump(.55)

    pump(); fixture_a = focus(host)
    cursor = w.POINT(); u.GetCursorPos(c.byref(cursor))
    env = dict(os.environ, FRIDAY_ISLAND_CONFIG=str(path))
    log = (output / "app.log").open("w", encoding="utf-8")
    executable = ROOT / 'island/src-tauri/target' / ('release' if release else 'debug') / 'friday-island.exe'
    app = subprocess.Popen([str(executable)],
                           cwd=ROOT / "island", env=env, stdout=log, stderr=log)
    hwnd = None
    evidence = {}
    try:
        def find_window(candidate, _):
            nonlocal hwnd
            pid = w.DWORD(); u.GetWindowThreadProcessId(candidate, c.byref(pid))
            title = c.create_unicode_buffer(128); u.GetWindowTextW(candidate, title, 128)
            if pid.value == app.pid and title.value == "FRIDAY Island": hwnd = candidate
            return True

        for _ in range(100):
            u.EnumWindows(CALLBACK(find_window), 0)
            if hwnd: break
            pump(.1)
        assert hwnd, "Island window did not start"
        pump(2)
        if online:
            assert authenticated.wait(5), 'Native release did not authenticate to isolated bridge'
            evidence['native_authenticated'] = True
        evidence["startup_passive"] = u.GetForegroundWindow() == fixture_a
        assert evidence["startup_passive"], "Startup stole focus"

        def region():
            handle = g.CreateRectRgn(0, 0, 0, 0)
            assert u.GetWindowRgn(hwnd, handle) > 0, "Missing native region"
            box = w.RECT(); g.GetRgnBox(handle, c.byref(box))
            result = (box.left, box.top, box.right, box.bottom)
            g.DeleteObject(handle)
            return result

        for _ in range(50):
            if region()[2] > 0: break
            pump(.1)

        bounds = w.RECT(); u.GetWindowRect(hwnd, c.byref(bounds))
        style = u.GetWindowLongPtrW(hwnd, -20)
        evidence["no_activate"] = bool(style & 0x08000000)
        evidence["tool_window"] = bool(style & 0x80)
        evidence["always_on_top"] = bool(style & 0x8)
        evidence["top_edge"] = bounds.top == 0
        evidence['dpi'] = u.GetDpiForWindow(hwnd)
        evidence['exe_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
        paths = [*sorted((ROOT / 'island/src').glob('*')), *sorted((ROOT / 'island/src-tauri/src').glob('*.rs')),
                 *[ROOT / 'island' / p for p in ['package.json', 'package-lock.json', 'index.html', 'tsconfig.json', 'vite.config.ts',
                    'src-tauri/Cargo.toml', 'src-tauri/Cargo.lock', 'src-tauri/build.rs', 'src-tauri/tauri.conf.json', 'src-tauri/capabilities/main.json']]]
        manifest = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
        evidence['source_sha256'] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        (output / 'source.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        with zipfile.ZipFile(output / 'source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for p in paths:
                if p.is_file(): archive.write(p, str(p.relative_to(ROOT)))
        evidence["rest_region"] = rest = region()
        evidence['rest_size'] = [bounds.right - bounds.left, bounds.bottom - bounds.top]
        assert evidence['rest_size'][0] < 400 * evidence['dpi'] / 96 and evidence['rest_size'][1] < 90 * evidence['dpi'] / 96
        assert all(evidence[k] for k in ["no_activate", "tool_window", "always_on_top", "top_edge"]), evidence
        handle = g.CreateRectRgn(0, 0, 0, 0); u.GetWindowRgn(hwnd, handle)
        assert not g.PtInRegion(handle, 0, 0), "Empty area blocks clicks"
        assert not g.PtInRegion(handle, rest[0] + 1, rest[3] - 1), "Rounded transparent corner blocks clicks"
        g.DeleteObject(handle)
        evidence["transparent_regions"] = True
        center = (bounds.left + bounds.right) // 2
        if '--measure' in sys.argv:
            import psutil
            process = psutil.Process(app.pid)

            def sample():
                result = {}
                for p in [process, *process.children(recursive=True)]:
                    try:
                        times = p.cpu_times()
                        result[p.pid] = times.user + times.system
                    except psutil.Error: pass
                return result

            pump(5)
            evidence['cpu_warmup_seconds'] = 5
            before = sample(); started = time.monotonic(); pump(5); after = sample()
            elapsed = time.monotonic() - started
            evidence['rest_cpu_percent_one_core'] = round(sum(max(0, value - before.get(pid, value)) for pid, value in after.items()) / elapsed * 100, 2)
            evidence['cpu_sample_seconds'] = round(elapsed, 2)
            evidence['measured_processes'] = len(after)
            evidence['cpu_by_pid'] = {str(pid): round(max(0, value - before.get(pid, value)) / elapsed * 100, 2) for pid, value in after.items()}
        u.SetCursorPos(center, 10); pump(.8)
        peek = region()
        evidence["hover_peek"] = peek[2] - peek[0] > rest[2] - rest[0] + 100
        evidence["hover_passive"] = u.GetForegroundWindow() == fixture_a
        assert evidence["hover_peek"] and evidence["hover_passive"], evidence
        u.SetCursorPos(center, 450)
        key([0x1B])
        key([0x11, 0x10, 0x12, 0x87])
        evidence["expand_focus"] = u.GetForegroundWindow() == hwnd
        assert evidence["expand_focus"], f"Explicit expand did not focus command input: {evidence}, foreground={u.GetForegroundWindow()}, island={hwnd}, region={region()}"
        key([0x11, 0x10, 0x12, 0x87])
        expanded = region(); evidence["expanded_region"] = expanded
        assert expanded[3] - expanded[1] > 100, "Second expand did not show card"
        key([0x1B])
        evidence["escape_restores_fixture"] = u.GetForegroundWindow() == fixture_a
        assert evidence["escape_restores_fixture"], "Esc did not restore previous focus"
        key([0x11, 0x10, 0x12, 0x86])
        sneak = region(); evidence["sneak_region"] = sneak
        assert u.GetForegroundWindow() == hwnd, "Sneak did not focus"
        sneak_bounds = w.RECT(); u.GetWindowRect(hwnd, c.byref(sneak_bounds))
        evidence["sneak_centered"] = abs((sneak_bounds.top + sneak_bounds.bottom) / 2 - u.GetSystemMetrics(1) / 2) < 3
        assert evidence["sneak_centered"]
        if online:
            for letter in 'NEXT': key([ord(letter)])
            key([0x0D])
            assert replies and 'DBMS' in replies[-1]['text'], f'Native command did not reach real bridge: {replies}'
            evidence['native_command_result'] = replies[-1]['text']
            key([0x11, 0x10, 0x12, 0x86])
        fixture_b = focus(other)
        pump(.6)
        evidence["click_elsewhere_keeps_focus"] = u.GetForegroundWindow() == fixture_b
        assert evidence["click_elsewhere_keeps_focus"], "Dismissal stole focus from newly selected app"
        focus(host); u.SetCursorPos(center, 10); pump(.8)
        key([0x1B])
        evidence["passive_escape"] = region()[2] - region()[0] < peek[2] - peek[0]
        assert evidence["passive_escape"], "Esc did not close passive Peek"
        evidence["pid"] = app.pid
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
        print("PASS: isolated Windows foreground, hotkeys, states and hit regions")
    finally:
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        app.terminate(); app.wait(timeout=10); log.close()
        u.SetCursorPos(cursor.x, cursor.y); u.DestroyWindow(host); u.DestroyWindow(other)
        stop.set()
        if server_thread: server_thread.join(timeout=5)
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
