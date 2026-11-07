import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { pluginCard } from '../src/plugin-card.ts';
import { replyDuration } from '../src/reply-state.ts';

const event = { topic: 'ui.card', plugin_id: 'smart_clipboard', payload: {
  title: 'Clipboard · Color', body: '#FF0000 · rgb(255, 0, 0)', ttl_s: 6,
  actions: [{ id: 'run', label: 'Copy result', payload: { token: 'opaque', copy: true } }],
} };

test('plugin capsule cards retain chips, explicit expiry and validated swatches', () => {
  const card = pluginCard(event)!;
  assert.equal(card.owner, 'smart_clipboard');
  assert.equal(card.swatch, '#FF0000');
  assert.equal(card.ttlMs, 6000);
  assert.deepEqual(card.actions[0].payload, { token: 'opaque', copy: true });
  assert.equal(replyDuration({ text: card.text, kind: 'reminder', ttlMs: card.ttlMs }), 6000);
});

test('untrusted plugin metadata cannot become markup, swatches or action paths', () => {
  assert.equal(pluginCard({ ...event, plugin_id: '../escape' }), null);
  assert.equal(pluginCard({ ...event, payload: { ...event.payload, body: 'x'.repeat(4001) } }), null);
  const card = pluginCard({ ...event, payload: { ...event.payload, body: 'url(https://example.com)',
    actions: [{ id: '../escape', label: 'Open' }] } })!;
  assert.equal(card.swatch, undefined);
  assert.deepEqual(card.actions, []);
  assert.equal(pluginCard({ ...event, plugin_id: 'another' })?.swatch, undefined);
});
