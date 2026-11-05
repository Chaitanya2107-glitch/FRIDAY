import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { PluginEvents } from '../src/plugin-events.ts';
import { matchesDismiss } from '../src/hotkeys.ts';

test('plugin event stream sends a header token and stops on cancellation', async () => {
  const original = globalThis.fetch;
  let url = ''; let init: RequestInit | undefined;
  let received!: (value: unknown) => void;
  const next = new Promise(resolve => { received = resolve; });
  const encoder = new TextEncoder();
  globalThis.fetch = (async (input, options) => {
    url = String(input); init = options;
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(encoder.encode(': hi\n\ndata: {"topic":"todo.changed","payload":{}}\n\n'));
      options?.signal?.addEventListener('abort', () => controller.close());
    } }), { status: 200 });
  }) as typeof fetch;
  const events = new PluginEvents(8000, 'secret-token', received);
  try {
    events.start();
    const event = await next as { topic: string };
    assert.equal(event.topic, 'todo.changed');
    assert.equal(url, 'http://127.0.0.1:8000/api/events');
    assert.deepEqual(init?.headers, { 'X-Friday-Token': 'secret-token' });
    events.stop();
    assert.equal(init?.signal?.aborted, true);
  } finally { events.stop(); globalThis.fetch = original; }
});

test('dismiss keys respect configured modifiers', () => {
  const event = { key: 'Escape', ctrlKey: false, altKey: false, shiftKey: false, metaKey: false };
  assert.equal(matchesDismiss(event), true);
  assert.equal(matchesDismiss(event, 'Ctrl+K'), false);
  assert.equal(matchesDismiss({ ...event, key: 'k', ctrlKey: true }, 'Ctrl+K'), true);
  assert.equal(matchesDismiss({ ...event, key: 'k', ctrlKey: true, altKey: true }, 'Ctrl+K'), false);
});
