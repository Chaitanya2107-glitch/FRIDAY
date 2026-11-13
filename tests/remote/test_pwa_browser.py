"""360px PWA smoke against a local mock that verifies real browser signatures."""
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from services.remote.app_shell import ASSETS, ROOT
from services.remote.security import RequestProofs, b64, key_id


def test_phone_at_360px(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    if not (ROOT / 'app.js').is_file():
        pytest.fail('Build the phone shell with npm run build:remote in island first.')
    state = dict(devices={}, commands=[], verified=0, revoked=False, refuse_revoke=True)
    proofs = RequestProofs()
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    fingerprint = 'sha256:' + hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    status = dict(reachable=True, battery=dict(percent=83, plugged=False), current_app='Visual Studio Code',
                  scene=dict(active='study'), focus=dict(remaining_s=1380), mood=dict(mood='happy'),
                  next_class=dict(subject='Applied Mathematics', start='10:30', faculty='Dr. Asha Rao', date='2026-11-14'), due_today=[{}])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log mock request payloads either.

        def reply(self, value, content_type='application/json', code=200):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch()

        def dispatch(self):
            path = urlsplit(self.path).path
            if path.startswith('/remote/app/'):
                name = path[len('/remote/app/'):]
                if name in ASSETS:
                    self.reply((ROOT / (name or 'index.html')).read_bytes(), ASSETS[name])
                    return
            try:
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                body = json.loads(raw) if raw else {}
                identity = self.headers['X-Device-Id']
                if path == '/remote/v1/pair':
                    assert body['token'] == 'mock-one-time-token' and body['pin'] == '123456'
                    row = dict(id=key_id(body['public_key']), public_key=body['public_key'], name=body['name'])
                    assert identity == row['id']
                    state['devices'][identity] = row
                row = state['devices'][identity]
                assert not state['revoked']
                proofs.verify(row, self.command, path, raw, {k.lower(): v for k, v in self.headers.items()})
                state['verified'] += 1
                if path.startswith('/remote/v1/pair'):
                    phase = 'awaiting_laptop' if path.endswith('/pair') else 'paired'
                    payload = dict(device_id=identity, nonce=self.headers['X-Nonce'], state=phase)
                    signature = key.sign(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode(), ec.ECDSA(hashes.SHA256()))
                    self.reply(dict(state=phase, proof=dict(payload=payload, public_key=public, signature=b64(signature))))
                elif path.endswith('/status'):
                    self.reply(status)
                elif path.endswith('/device'):
                    self.reply(dict(name=row['name']))
                elif path.endswith('/events'):
                    self.reply(b'event: focus.tick\ndata: {"remaining_s":1380}\n\n', 'text/event-stream')
                elif path.endswith('/schedule'):
                    self.reply(dict(today=[status['next_class']], tomorrow=[], assignments=[dict(what='Physics report', due='2026-11-14')], exams=[]))
                elif path.endswith('/activity'):
                    self.reply(dict(entries=[dict(command='start_focus', time=time.time(), risk='safe', result='completed')]))
                elif path.endswith('/chat'):
                    assert body['command'] == 'ask'
                    self.reply(b'event: reply\ndata: {"text":"Hello from FRIDAY"}\n\nevent: done\ndata: {}\n\n', 'text/event-stream')
                elif path.endswith('/commands'):
                    state['commands'].append(body['command'])
                    if body['command'] == 'lock_pc':
                        self.reply(dict(result='approval_required', challenge='mock-challenge', command='lock_pc', args={}, expires_in=60, pin_required=True))
                    elif body['command'] == 'revoke_self':
                        if state['refuse_revoke']:
                            self.reply({}, code=404)
                        else:
                            state['revoked'] = True
                            self.reply(dict(result='completed', data=dict(revoked=True)))
                    else:
                        self.reply(dict(result='completed', data=dict(text='Done.')))
                elif path.endswith('/approve'):
                    assert body['challenge'] == 'mock-challenge' and body['approval']['pin'] == '123456'
                    self.reply(dict(result='completed'))
                else:
                    self.reply({}, code=404)
            except Exception:
                self.reply({}, code=404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    evidence = Path(__file__).resolve().parents[2] / 'tasks/remote-pwa'
    evidence.mkdir(exist_ok=True)
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except playwright.Error as error:
                if 'Executable doesn\'t exist' in str(error):
                    pytest.skip('Playwright installed; Chromium executable missing.')
                raise
            context = browser.new_context(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True)
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(origin + '/remote/app/')
            page.locator('#pairing').wait_for(state='visible')
            page.screenshot(path=str(evidence / 'pairing-360.png'), full_page=True)
            page.locator('#scan').click()
            page.locator('#pair-code').fill(json.dumps(dict(url=origin, token='mock-one-time-token', fingerprint=fingerprint,
                                                         expires=time.time() + 120, signing_prefix='/remote')))
            page.locator('#new-pin').fill('123456')
            page.locator('#pair-form button[type=submit]').click()
            page.locator('#panel').wait_for(state='visible', timeout=15000)
            page.wait_for_function("document.querySelector('#connection').textContent.includes('Laptop reachable')")
            assert page.locator('#faculty').inner_text().startswith('Dr. Asha Rao')
            assert page.locator('#battery').inner_text().startswith('83%')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(evidence / 'home-360.png'), full_page=True)
            # The restored browser CryptoKey must remain non-extractable after reload.
            page.reload(); page.locator('#panel').wait_for(state='visible')
            page.wait_for_function("document.querySelector('#connection').textContent.includes('Laptop reachable')")
            assert page.evaluate("""async () => {
                const db = await new Promise(resolve => { const r=indexedDB.open('friday-remote'); r.onsuccess=()=>resolve(r.result); });
                const row=await new Promise(resolve=>{ const r=db.transaction('private').objectStore('private').get('identity'); r.onsuccess=()=>resolve(r.result); });
                db.close();
                try { await crypto.subtle.exportKey('pkcs8', row.key); return false; } catch { return !row.key.extractable; }
            }""")
            page.locator('[data-command="start_focus"]').click()
            page.wait_for_function("document.querySelector('#notice').textContent === 'Done.'")
            page.locator('[data-command="lock_pc"]').click()
            page.locator('#confirm').wait_for(state='visible')
            page.screenshot(path=str(evidence / 'confirm-360.png'), full_page=True)
            page.locator('#approval-pin').fill('123456'); page.locator('#confirm-form button[type=submit]').click()
            page.locator('#confirm').wait_for(state='hidden')
            page.locator('[data-screen="chat"]').click(); page.locator('#message').fill('Hello')
            page.locator('#send').click(); page.wait_for_function("document.querySelector('#messages').textContent.includes('Hello from FRIDAY')")
            page.screenshot(path=str(evidence / 'chat-360.png'), full_page=True)
            page.locator('[data-screen="schedule"]').click()
            page.wait_for_function("document.querySelector('#schedule-list').textContent.includes('Applied Mathematics')")
            page.locator('[data-day="assignments"]').click()
            assert 'Physics report' in page.locator('#schedule-list').inner_text()
            page.locator('[data-screen="activity"]').click()
            page.wait_for_function("document.querySelector('#activity-list').textContent.includes('start focus')")
            page.locator('[data-screen="devices"]').click()
            page.wait_for_function("document.querySelector('#device-name').textContent === 'My phone'")
            page.on('dialog', lambda dialog: dialog.accept())
            page.locator('#revoke').click()
            page.wait_for_function("document.querySelector('#notice').textContent.includes('Revocation was not confirmed')")
            assert page.locator('#panel').is_visible()
            page.locator('[data-screen="home"]').click()
            page.evaluate('navigator.serviceWorker.ready')
            page.wait_for_function('navigator.serviceWorker.controller !== null')
            context.set_offline(True); page.reload()
            page.locator('#panel').wait_for(state='visible')
            page.wait_for_function("document.querySelector('#connection').textContent.includes('last known status')")
            assert page.locator('[data-command="lock_pc"]').is_disabled()
            assert 'Applied Mathematics' in page.locator('#next-class').inner_text()
            page.screenshot(path=str(evidence / 'offline-360.png'), full_page=True)
            context.set_offline(False)
            page.wait_for_function("document.querySelector('#connection').textContent.includes('Laptop reachable')")
            state['refuse_revoke'] = False
            page.locator('[data-screen="devices"]').click(); page.locator('#revoke').click()
            page.locator('#pairing').wait_for(state='visible')
            assert state['revoked'] and state['verified'] >= 10
            assert not errors
            context.close(); browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
