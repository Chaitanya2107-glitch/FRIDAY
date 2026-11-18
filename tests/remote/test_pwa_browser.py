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
    state = dict(devices={}, commands=[], queued={}, verified=0, revoked=False, refuse_revoke=True,
                 care_confirmed=False, care_can_log=False, care_taps=[], care_question_gets=0,
                 care_pending=True, care_answers=[], chat_texts=[], goal_gets=0, goal_calls=[], goal_receipts=set())
    proofs = RequestProofs()
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    fingerprint = 'sha256:' + hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    status = dict(reachable=True, battery=dict(percent=83, plugged=False), current_app='Visual Studio Code',
                  scene=dict(active='study'), focus=dict(remaining_s=1380), mood=dict(mood='happy'),
                  presence=dict(state='at_desk', reason='Laptop input is recent.', confidence=.84, since=time.time()-300, data_available=True),
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
                elif path.endswith('/timeline'):
                    self.reply(dict(day='2026-11-14', segments=[dict(device='laptop', app='Editor', category='coding', start=time.time()-600, end=time.time()), dict(device='phone', app='com.example.study', category='study', start=time.time()-300, end=time.time())]))
                elif path.endswith('/events'):
                    presence = dict(state='at_desk', reason='Laptop input remains active.', confidence=.9, since=time.time()-300)
                    stream = 'event: focus.tick\ndata: {"remaining_s":1380}\n\nevent: presence.changed\ndata: ' + json.dumps(presence) + '\n\n'
                    self.reply(stream.encode(), 'text/event-stream')
                elif path.endswith('/schedule'):
                    self.reply(dict(today=[status['next_class']], tomorrow=[], assignments=[dict(what='Physics report', due='2026-11-14')], exams=[]))
                elif path.endswith('/activity'):
                    self.reply(dict(entries=[dict(command='start_focus', time=time.time(), risk='safe', result='completed')]))
                elif path.endswith('/chat'):
                    assert body['command'] == 'ask'
                    state['chat_texts'].append(body['args']['text'])
                    private = body['args']['text'] == 'Private care reply'
                    value = dict(text='Private care reply stays local.' if private else 'Hello from FRIDAY', allow_speech=not private)
                    self.reply(('event: reply\ndata: ' + json.dumps(value) + '\n\nevent: done\ndata: {}\n\n').encode(), 'text/event-stream')
                elif path.endswith('/queue'):
                    assert set(body) == {'id', 'created', 'expires_at', 'command', 'args'}
                    assert body['command'] in {'start_focus', 'stop_focus', 'set_scene', 'add_note', 'ring_laptop'}
                    assert 0 < body['expires_at'] - body['created'] <= 86400
                    if body['id'] not in state['queued']:
                        state['queued'][body['id']] = body
                        state['commands'].append(body['command'])
                    self.reply(dict(result='completed', data=dict(text='Done.')))
                elif path.endswith('/commands'):
                    state['commands'].append(body['command'])
                    if body['command'] == 'care_status':
                        self.reply(dict(result='completed', data=dict(wellbeing=dict(confirmed=state['care_confirmed'],
                            can_log=state['care_can_log'], logged_today=bool(state['care_taps'])))))
                    elif body['command'] == 'care_checkin':
                        assert state['care_confirmed'] and state['care_can_log'] and set(body['args']) == {'score'}
                        assert type(body['args']['score']) is int and 1 <= body['args']['score'] <= 5
                        state['care_taps'].append(body['args']['score'])
                        self.reply(dict(result='completed', data=dict(recorded=True)))
                    elif body['command'] == 'care_question':
                        assert body['args'] == {}
                        state['care_question_gets'] += 1
                        self.reply(dict(result='completed', data=dict(pending=state['care_pending'], id='a' * 32,
                            text='About 50 minutes on short videos in your study block. Want a 15-minute reminder, or leave it?',
                            choices=['remind15', 'leave'])))
                    elif body['command'] == 'care_answer':
                        assert body['args']['id'] == 'a' * 32 and body['args']['choice'] in {'remind15', 'leave'}
                        assert set(body['args']) == {'id', 'choice'}
                        state['care_answers'].append(body['args']); state['care_pending'] = False
                        self.reply(dict(result='completed', data=dict(recorded=True)))
                    elif body['command'] == 'goal_status':
                        assert body['args'] == {}
                        state['goal_gets'] += 1
                        self.reply(dict(result='completed', data=dict(goals=[
                            dict(id=1, title='Private water goal', unit='glasses', manual=True,
                                 done=len(state['goal_receipts']), target=8),
                            dict(id=2, title='Study', unit='minutes', manual=False, done=None, target=25)])))
                    elif body['command'] == 'goal_log':
                        args = body['args']
                        assert set(args) == {'id', 'value', 'receipt'} and args['id'] == 1 and args['value'] == 1
                        assert len(args['receipt']) == 32 and all(char in '0123456789abcdef' for char in args['receipt'])
                        state['goal_calls'].append(args); state['goal_receipts'].add(args['receipt'])
                        self.reply(dict(result='completed', data=dict(recorded=True)))
                    elif body['command'] == 'lock_pc':
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
            page.wait_for_function("document.querySelector('#presence-confidence').textContent === '90% confidence'")
            assert page.locator('#presence-state').inner_text() == 'At desk'
            assert page.locator('#presence-reason').inner_text() == 'Laptop input remains active.'
            page.wait_for_function("document.querySelector('#wellbeing-status').textContent.includes('Off until')")
            assert page.locator('#wellbeing-options').is_hidden()
            assert not state['care_taps'] and state['care_question_gets'] == 0 and state['goal_gets'] == 0
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
            # Confirmation/window come from the laptop; the tap never uses chat, speech or a queue.
            state['care_confirmed'] = state['care_can_log'] = True
            page.locator('[data-screen="home"]').click()
            page.locator('[data-wellbeing-score="4"]').wait_for(state='visible')
            page.wait_for_function("!document.querySelector('[data-wellbeing-score=\"4\"]').disabled")
            page.evaluate("() => { window.__spoken = []; window.speechSynthesis.speak = value => window.__spoken.push(value.text); }")
            page.locator('[data-wellbeing-score="4"]').click()
            page.wait_for_function("document.querySelector('#wellbeing-status').textContent.includes('saved on your laptop')")
            assert state['care_taps'] == [4] and not state['chat_texts']
            assert state['care_question_gets'] == 0
            assert page.locator('#private-check-text').inner_text() == ''
            page.locator('#view-private-check').click()
            page.wait_for_function("document.querySelector('#private-check-text').textContent.includes('short videos')")
            assert state['care_question_gets'] == 1
            assert page.evaluate('window.__spoken') == []
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(evidence / 'care-360.png'), full_page=True)
            page.locator('[data-screen="chat"]').click()
            assert page.locator('#private-check-details').is_hidden()
            assert page.locator('#private-check-text').inner_text() == ''
            page.locator('[data-screen="home"]').click()
            assert state['care_question_gets'] == 1
            page.locator('#view-private-check').click()
            page.wait_for_function("document.querySelector('#private-check-text').textContent.includes('short videos')")
            page.locator('[data-care-choice="leave"]').click()
            page.wait_for_function("document.querySelector('#private-check-status').textContent.includes('choice is saved locally')")
            assert state['care_answers'] == [dict(id='a' * 32, choice='leave')]
            assert page.locator('#private-check-text').inner_text() == ''
            assert page.evaluate("""async () => {
                const db = await new Promise(resolve => { const r=indexedDB.open('friday-remote'); r.onsuccess=()=>resolve(r.result); });
                const rows=await new Promise(resolve=>{const r=db.transaction('private').objectStore('private').getAll();r.onsuccess=()=>resolve(r.result);});
                db.close(); const text=JSON.stringify(rows); return !text.includes('"score"') && !text.includes('short videos');
            }""")
            assert state['goal_gets'] == 0
            with proofs.lock:
                proofs.requests.clear()  # Each UI scenario gets a fresh mock rate window; signature/nonce checks remain real.
            page.locator('#view-goals').click()
            page.wait_for_function("document.querySelector('#goals-list').textContent.includes('Private water goal')")
            assert state['goal_gets'] == 1 and page.locator('#goals-list button').count() == 1
            assert 'Progress unavailable' in page.locator('#goals-list').inner_text()
            assert page.locator('#goals-list button').bounding_box()['height'] >= 48
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(evidence / 'goals-360.png'), full_page=True)
            page.locator('[data-screen="chat"]').click()
            assert page.locator('#goals-list').inner_text() == ''
            page.locator('[data-screen="home"]').click()
            assert state['goal_gets'] == 1
            page.locator('#view-goals').click()
            page.wait_for_function("document.querySelector('#goals-list').textContent.includes('Private water goal')")
            page.evaluate("""() => {
                Object.defineProperty(document, 'hidden', {configurable:true, value:true});
                document.dispatchEvent(new Event('visibilitychange'));
            }""")
            assert page.locator('#goals-list').inner_text() == ''
            page.evaluate("() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); }")
            page.wait_for_function("document.querySelector('#connection').textContent.includes('Laptop reachable')")
            assert state['goal_gets'] == 2
            held = []

            def hold_log(route):
                if route.request.post_data_json.get('command') == 'goal_log' and not held:
                    held.append(route)
                else:
                    route.continue_()

            page.route('**/v1/commands', hold_log)
            page.locator('#view-goals').click()
            with page.expect_request(lambda req: req.url.endswith('/v1/commands') and req.post_data_json.get('command') == 'goal_log'):
                page.locator('#goals-list button').click()
            assert page.locator('#goals-list button').is_disabled() and page.locator('#view-goals').is_disabled()
            assert 'Saved' not in page.locator('#goals-status').inner_text()
            assert len(held) == 1
            held[0].fetch()  # The laptop records it, but its reply never reaches the browser.
            held[0].abort('failed')
            page.wait_for_function("document.querySelector('#goals-status').textContent.includes('not confirmed')")
            assert page.locator('#goals-list').inner_text() == '' and len(state['goal_calls']) == 1
            page.evaluate("window.dispatchEvent(new Event('online'))")
            page.wait_for_function("document.querySelector('#connection').textContent.includes('Laptop reachable')")
            assert len(state['goal_calls']) == 1  # Reconnection never retries a private log.
            page.locator('#view-goals').click()
            retry = page.locator('#goals-list button')
            retry.wait_for(state='visible')
            assert retry.inner_text() == 'Retry previous +1 glasses'
            assert '1 / 8 glasses' in page.locator('#goals-list').inner_text()
            retry.click()
            page.wait_for_function("document.querySelector('#goals-status').textContent.includes('Saved on your laptop')")
            assert len(state['goal_calls']) == 2 and state['goal_calls'][0] == state['goal_calls'][1]
            assert len(state['goal_receipts']) == 1 and page.locator('#goals-list').inner_text() == ''
            assert not state['chat_texts'] and page.evaluate('window.__spoken') == []
            page.unroute('**/v1/commands', hold_log)
            with proofs.lock:
                proofs.requests.clear()
            assert page.evaluate("""async () => {
                const db = await new Promise(resolve => {const r=indexedDB.open('friday-remote');r.onsuccess=()=>resolve(r.result);});
                const rows=await new Promise(resolve=>{const r=db.transaction('private').objectStore('private').getAll();r.onsuccess=()=>resolve(r.result);});
                db.close(); const value=JSON.stringify(rows); return !value.includes('Private water goal') && !value.includes('"receipt"');
            }""")
            page.locator('[data-command="start_focus"]').click()
            page.wait_for_function("document.querySelector('#notice').textContent === 'Done.'")
            page.locator('[data-command="lock_pc"]').click()
            page.locator('#confirm').wait_for(state='visible')
            page.screenshot(path=str(evidence / 'confirm-360.png'), full_page=True)
            page.locator('#approval-pin').fill('123456'); page.locator('#confirm-form button[type=submit]').click()
            page.locator('#confirm').wait_for(state='hidden')
            page.locator('[data-screen="chat"]').click(); page.locator('#message').fill('Hello')
            page.locator('#speak').check()
            page.locator('#send').click(); page.wait_for_function("document.querySelector('#messages').textContent.includes('Hello from FRIDAY')")
            assert page.evaluate('window.__spoken') == ['Hello from FRIDAY']
            page.locator('#message').fill('Private care reply'); page.locator('#send').click()
            page.wait_for_function("document.querySelector('#messages').textContent.includes('Private care reply stays local.')")
            assert page.evaluate('window.__spoken') == ['Hello from FRIDAY']
            page.screenshot(path=str(evidence / 'chat-360.png'), full_page=True)
            page.locator('[data-screen="schedule"]').click()
            page.wait_for_function("document.querySelector('#schedule-list').textContent.includes('Applied Mathematics')")
            page.locator('[data-day="assignments"]').click()
            assert 'Physics report' in page.locator('#schedule-list').inner_text()
            page.locator('[data-screen="timeline"]').click()
            page.wait_for_function("document.querySelector('#timeline-list').textContent.includes('com.example.study')")
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(evidence / 'timeline-360.png'), full_page=True)
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
            assert page.locator('#presence-state').inner_text() == 'Last known · At desk'
            assert 'Last known estimate.' in page.locator('#presence-reason').inner_text()
            assert page.locator('[data-command="lock_pc"]').is_disabled()
            assert page.locator('[data-wellbeing-score="4"]').is_disabled()
            assert page.locator('#view-private-check').is_disabled()
            assert page.locator('#view-goals').is_disabled() and page.locator('#goals-list').inner_text() == ''
            assert 'care_checkin' not in [row['command'] for row in state['queued'].values()]
            assert 'care_answer' not in [row['command'] for row in state['queued'].values()]
            assert 'goal_log' not in [row['command'] for row in state['queued'].values()]
            assert 'goal_status' not in [row['command'] for row in state['queued'].values()]
            assert page.locator('[data-command="start_focus"]').is_enabled()
            before = state['commands'].count('start_focus')
            page.locator('[data-command="start_focus"]').click()
            page.wait_for_function("document.querySelector('#waiting-title').textContent === '1 action waiting'")
            assert state['commands'].count('start_focus') == before
            page.reload(); page.locator('#panel').wait_for(state='visible')
            page.wait_for_function("document.querySelector('#waiting-title').textContent === '1 action waiting'")
            page.locator('[data-command="ring_laptop"]').click()
            page.wait_for_function("document.querySelector('#waiting-title').textContent === '2 actions waiting'")
            page.locator('#waiting-list .item').filter(has_text='ring laptop').get_by_role('button').click()
            page.wait_for_function("document.querySelector('#waiting-title').textContent === '1 action waiting'")
            assert page.evaluate("""async () => {
                const db = await new Promise(resolve => { const r=indexedDB.open('friday-remote-queue'); r.onsuccess=()=>resolve(r.result); });
                const rows=await new Promise(resolve=>{const r=db.transaction('commands').objectStore('commands').getAll();r.onsuccess=()=>resolve(r.result);});
                db.close(); return rows.length === 1 && rows[0].command === 'start_focus';
            }""")
            assert 'Applied Mathematics' in page.locator('#next-class').inner_text()
            page.screenshot(path=str(evidence / 'offline-360.png'), full_page=True)
            context.set_offline(False)
            page.wait_for_function("document.querySelector('#connection').textContent.includes('Laptop reachable')")
            page.locator('#waiting').wait_for(state='hidden')
            assert state['commands'].count('start_focus') == before + 1
            assert 'ring_laptop' not in state['commands']
            state['refuse_revoke'] = False
            page.locator('[data-screen="devices"]').click(); page.locator('#revoke').click()
            page.locator('#pairing').wait_for(state='visible')
            assert state['revoked'] and state['verified'] >= 10
            assert not errors
            context.close(); browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
