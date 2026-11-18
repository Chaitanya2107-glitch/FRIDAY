import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-ignore Browser module is shared with the installed phone shell.
import { CommandQueue, queuedCommand, queueable, QUEUE_INTERVAL_MS } from '../remote/queue.mjs';

test('gateway outages and interrupted replies wait, while P0 refusals stop retrying', async () => {
  const originalFetch = globalThis.fetch;
  Object.defineProperty(globalThis, 'location', { configurable: true, value: { pathname: '/remote/app/' } });
  // @ts-ignore The same browser transport is used by the installable shell.
  const { request } = await import('../remote/transport.mjs');
  // @ts-ignore Public key export remains permitted; the private key stays non-extractable.
  const { generateIdentity } = await import('../remote/signing.mjs');
  const identity = await generateIdentity('Test phone');
  try {
    for (const status of [502, 503, 504]) {
      globalThis.fetch = async () => new Response('{}', { status });
      await assert.rejects(request(identity, 'POST', 'queue', {}), (error: any) => error.networkUnavailable === true);
    }
    globalThis.fetch = async () => new Response('{}', { status: 404 });
    await assert.rejects(request(identity, 'POST', 'queue', {}), (error: any) => error.requestRefused === true && !error.networkUnavailable);
    globalThis.fetch = async () => ({ ok: true, json: async () => { throw new TypeError('Connection lost'); } }) as Response;
    await assert.rejects(request(identity, 'POST', 'queue', {}), (error: any) => error.networkUnavailable === true);
    globalThis.fetch = async () => new Response('{invalid', { status: 200 });
    await assert.rejects(request(identity, 'POST', 'queue', {}), SyntaxError);
  } finally {
    globalThis.fetch = originalFetch;
    Reflect.deleteProperty(globalThis, 'location');
  }
});

function memoryStore() {
  const rows = new Map<string, any>();
  return {
    list: async () => [...rows.values()].map(row => structuredClone(row)),
    put: async (row: any) => { rows.set(row.id, structuredClone(row)); },
    remove: async (id: string) => { rows.delete(id); },
    clear: async () => { rows.clear(); },
  };
}
test('only finite safe commands can be queued; confirmation and chat never enter storage', async () => {
  const store = memoryStore(), queue = new CommandQueue(store, () => assert.fail('not sent'));
  for (const command of ['lock_pc', 'sleep_pc', 'open_app', 'send_message', 'delete_note', 'phone_forget', 'ask', 'ask_friday', 'shell', 'revoke_self']) {
    assert.equal(queueable(command), false);
    await assert.rejects(queue.enqueue(command));
  }
  assert.deepEqual(await store.list(), []);
  assert.equal(queuedCommand('ring_laptop', {}, undefined, 100).expires_at, 1000);
  for (const ttl of [0, -1, 86401, Infinity, 1.5]) assert.throws(() => queuedCommand('ring_laptop', {}, ttl, 100));
  assert.equal(queuedCommand('ring_laptop', {}, 86400, 100).expires_at, 86500);
});
test('drain sends oldest first, preserves IDs over a lost response, and paces requests', async () => {
  const store = memoryStore(), sent: any[] = [], waits: number[] = [];
  const first = queuedCommand('start_focus', {}, 900, 100), second = queuedCommand('ring_laptop', {}, 900, 110);
  await store.put(second); await store.put(first);
  let lost = true;
  const queue = new CommandQueue(store, async (envelope: any) => {
    sent.push(envelope);
    if (lost) { lost = false; throw Object.assign(Error('network'), { networkUnavailable: true }); }
    return { result: 'completed' };
  }, { clock: () => 120, wait: async (ms: number) => { waits.push(ms); } });
  await queue.drain();
  assert.equal((await store.list()).length, 2);
  await queue.drain();
  assert.deepEqual(sent.map(row => row.id), [first.id, first.id, second.id]);
  assert.equal(sent[0].created, 100);
  assert.equal('state' in sent[0], false);
  assert.equal(QUEUE_INTERVAL_MS >= 2200, true);
  assert.deepEqual(waits, [QUEUE_INTERVAL_MS, QUEUE_INTERVAL_MS]);
  assert.deepEqual(await store.list(), []);
});
test('expired, refused, and uncertain outcomes never run or retry', async () => {
  const store = memoryStore(); let calls = 0;
  await store.put(queuedCommand('start_focus', {}, 10, 100));
  const queue = new CommandQueue(store, async () => { calls++; return { result: 'uncertain' }; }, { clock: () => 120, wait: async () => {} });
  await queue.drain(); assert.equal(calls, 0);
  assert.equal((await queue.rows())[0].state, 'expired');
  await queue.enqueue('ring_laptop'); await queue.drain(); await queue.drain();
  assert.equal(calls, 1); assert.equal((await queue.rows())[1].state, 'uncertain');
  const refused = new CommandQueue(store, async () => { calls++; throw Object.assign(Error('404'), { requestRefused: true }); }, { clock: () => 120, wait: async () => {} });
  await refused.enqueue('stop_focus'); await refused.drain(); await refused.drain();
  assert.equal(calls, 2);
  assert.equal((await refused.rows()).filter((row: any) => row.state === 'waiting').length, 0);
});
test('commands created within one second follow durable insertion sequence, not random UUID order', async () => {
  const store = memoryStore(), sent: string[] = [];
  await store.put({ ...queuedCommand('ring_laptop', {}, 900, 100), id: 'a', sequence: 2 });
  await store.put({ ...queuedCommand('start_focus', {}, 900, 100), id: 'z', sequence: 1 });
  const queue = new CommandQueue(store, async (row: any) => { sent.push(row.id); return { result: 'completed' }; }, { clock: () => 120, wait: async () => {} });
  await queue.drain(); assert.deepEqual(sent, ['z', 'a']);
});
test('expiry and cancellation while draining win before another request is sent', async () => {
  const store = memoryStore(); let now = 100;
  const queue = new CommandQueue(store, async () => ({ result: 'completed' }), {
    clock: () => now,
    wait: async () => { now += 20; },
  });
  await queue.enqueue('start_focus', {}, 10); await queue.enqueue('ring_laptop', {}, 11);
  await queue.drain();
  assert.equal((await queue.rows()).length, 1);
  assert.equal((await queue.rows())[0].state, 'expired');
  await store.clear(); now = 100; let sent = 0;
  const second = queuedCommand('ring_laptop', {}, 900, 101);
  await store.put(queuedCommand('start_focus', {}, 900, 100)); await store.put(second);
  const cancelled = new CommandQueue(store, async () => { sent++; return { result: 'completed' }; }, {
    clock: () => now, wait: async () => { await store.remove(second.id); },
  });
  await Promise.all([cancelled.drain(), cancelled.drain()]);
  assert.equal(sent, 1); assert.deepEqual(await store.list(), []);
});
