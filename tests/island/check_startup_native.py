"""Owned fake bridge lifecycle: no owner DB, provider or sign-in registry writes."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import winreg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_apps_native import ROOT, port
from check_native import u
import psutil
from playwright.sync_api import sync_playwright


def login_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            return winreg.QueryValueEx(key, 'FRIDAYIsland')
    except FileNotFoundError: return None


def main():
    output = ROOT / 'tasks/island-startup-native'; output.mkdir(exist_ok=True)
    registry_before = login_value()
    evidence = {}
    with tempfile.TemporaryDirectory(dir=output) as directory:
        folder = Path(directory)
        scripts = folder / 'venv/Scripts'; scripts.mkdir(parents=True)
        shutil.copyfile(ROOT/'venv/Scripts/python.exe', scripts/'python.exe')
        shutil.copyfile(ROOT/'venv/pyvenv.cfg', folder/'venv/pyvenv.cfg')
        module = folder/'services/friday_island_server'; module.mkdir(parents=True)
        (folder/'services/__init__.py').write_text('')
        (module/'__init__.py').write_text('')
        (module/'__main__.py').write_text('''import argparse,json,socket
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--config');a=p.parse_args()
cfg=json.loads(Path(a.config).read_text());s=socket.socket();s.bind(('127.0.0.1',cfg['connection']['port']));s.listen();s.settimeout(.2)
while not Path('stop').exists():
    try: c,_=s.accept();c.close()
    except socket.timeout: pass
''', encoding='utf-8')
        config_path = folder/'config.json'
        bridge_port = port()
        config_path.write_text(json.dumps({'connection': {'port': bridge_port}, 'startup': {'manage_bridge': True, 'backend_root': str(folder)},
                                         'hotkeys': {'sneak':'Ctrl+Shift+Alt+F23','expand':'Ctrl+Shift+Alt+F24'}}), encoding='utf-8')
        debug_port = port()
        env = dict(os.environ, FRIDAY_ISLAND_CONFIG=str(config_path), FRIDAY_ISLAND_MANAGE_BRIDGE='1',
                   WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={debug_port} --remote-debugging-address=127.0.0.1')
        exe = ROOT/'island/src-tauri/target/release/friday-island.exe'
        app = external = browser = None
        log = (output/'app.log').open('w', encoding='utf-8')
        try:
            with sync_playwright() as playwright:
                initial_focus = u.GetForegroundWindow()
                app = subprocess.Popen([str(exe), '--background'], cwd=ROOT/'island', env=env, stdout=log, stderr=log)
                for _ in range(100):
                    try:
                        browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{debug_port}', timeout=400);break
                    except Exception:
                        assert app.poll() is None, 'Island exited before inspector was ready'; time.sleep(.1)
                assert browser
                page = browser.contexts[0].pages[0]
                page.wait_for_function('window.__TAURI_INTERNALS__?.invoke !== undefined')
                def invoke(command, args=None):
                    return page.evaluate('([command,args])=>window.__TAURI_INTERNALS__.invoke(command,args)', [command,args or {}])
                def wait_for(predicate, seconds=20):
                    until = time.monotonic()+seconds
                    while time.monotonic()<until:
                        state=invoke('startup_status')
                        if predicate(state): return state
                        page.wait_for_timeout(150)
                    raise AssertionError(state)
                def manage(enabled):
                    config=invoke('get_config');config['startup']['manage_bridge']=enabled
                    invoke('save_config', {'next':config})
                def free(ident):
                    with socket.socket() as probe:
                        try: probe.bind(('127.0.0.1',ident));return True
                        except OSError: return False
                def assert_stopped(owned, listen_port):
                    until=time.monotonic()+5
                    while time.monotonic()<until:
                        if all(not p.is_running() for p in owned) and free(listen_port): return
                        time.sleep(.1)
                    raise AssertionError('Owned bridge descendant or listener survived cleanup')
                state = wait_for(lambda s:s['phase']=='managed' and s['owned_pid'])
                child = state['owned_pid']; evidence['auto_start'] = True
                assert u.GetForegroundWindow()==initial_focus, 'Island or owned bridge startup stole focus'
                evidence['owned_startup_is_passive'] = True
                before_mode=invoke('runtime_status')['mode'];before_focus=u.GetForegroundWindow()
                subprocess.run([str(exe),'--background'],cwd=ROOT/'island',env=env,check=True,timeout=5)
                page.wait_for_timeout(300)
                assert invoke('runtime_status')['mode']==before_mode
                assert u.GetForegroundWindow()==before_focus
                evidence['background_duplicate_is_passive'] = True
                assert str(config_path).lower() in ' '.join(psutil.Process(child).cmdline()).lower()
                psutil.Process(child).terminate()
                state=wait_for(lambda s:s['phase']=='managed' and s['owned_pid'] and s['owned_pid']!=child)
                child=state['owned_pid']; evidence['crash_recovery'] = True
                invoke('restart_bridge')
                state=wait_for(lambda s:s['phase']=='managed' and s['owned_pid'] and s['owned_pid']!=child)
                child=state['owned_pid'];evidence['explicit_restart'] = True
                old_port=bridge_port;bridge_port=port()
                edited=json.loads(config_path.read_text());edited['connection']['port']=bridge_port
                config_path.write_text(json.dumps(edited),encoding='utf-8')
                invoke('reload_config')
                state=wait_for(lambda s:s['phase']=='managed' and s['owned_pid'] and s['owned_pid']!=child)
                child=state['owned_pid'];assert free(old_port) and not free(bridge_port)
                evidence['reload_reconfigures_owned_bridge'] = True
                config=invoke('get_config');config['startup']['backend_root']=str(folder/'missing');invoke('save_config',{'next':config})
                wait_for(lambda s:s['phase']=='error' and s['error'] and not s['owned_pid'])
                assert free(bridge_port)
                config=invoke('get_config');config['startup']['backend_root']=str(folder);invoke('save_config',{'next':config})
                state=wait_for(lambda s:s['phase']=='managed' and s['owned_pid']);child=state['owned_pid']
                evidence['missing_backend_is_recoverable'] = True
                owned=[psutil.Process(child), *psutil.Process(child).children(recursive=True)]
                manage(False);wait_for(lambda s:s['phase']=='disabled')
                assert_stopped(owned,bridge_port)
                evidence['disable_stops_owned'] = True
                external=subprocess.Popen([str(scripts/'python.exe'),'-B','-m','services.friday_island_server','--config',str(config_path)], cwd=folder, stdout=log, stderr=log)
                page.wait_for_timeout(500);assert external.poll() is None
                manage(True);wait_for(lambda s:s['phase']=='external' and s['owned_pid'] is None)
                invoke('restart_bridge');page.wait_for_timeout(1200)
                assert external.poll() is None
                assert invoke('startup_status')['owned_pid'] is None
                evidence['external_reuse_no_kill'] = True
                try: invoke('set_login', {'enabled':True});raise AssertionError('Isolated run changed sign-in')
                except Exception as error: assert 'isolated config' in str(error)
                assert login_value()==registry_before; evidence['registry_untouched'] = True
                (folder/'stop').touch();external.wait(timeout=5);external=None;(folder/'stop').unlink()
                state=wait_for(lambda s:s['phase']=='managed' and s['owned_pid']);child=state['owned_pid']
                owned=[psutil.Process(child), *psutil.Process(child).children(recursive=True)]
                app.terminate();app.wait(timeout=5)
                assert_stopped(owned,bridge_port)
                evidence['hard_exit_job_cleanup'] = True
        finally:
            if app and app.poll() is None: app.terminate();app.wait(timeout=5)
            if external and external.poll() is None: (folder/'stop').touch();external.wait(timeout=5)
            log.close()
        assert login_value()==registry_before
    (output/'evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence,indent=2));print('PASS: native bridge startup/recovery/ownership/job cleanup; registry unchanged')


if __name__=='__main__': main()
