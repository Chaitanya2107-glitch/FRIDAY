import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { localSuggestions, readReminder, transition } from '../src/state.ts';

test('four states and repeat-expand cycle', () => {
  assert.equal(transition('rest', 'hover'), 'peek');
  assert.equal(transition('rest', 'expand'), 'peek');
  assert.equal(transition('peek', 'expand'), 'expanded');
  assert.equal(transition('expanded', 'expand'), 'rest');
  assert.equal(transition('rest', 'settings'), 'expanded');
  assert.equal(transition('peek', 'projects'), 'expanded');
  for (const mode of ['rest', 'peek', 'expanded', 'hidden', 'sneak'] as const) {
    assert.equal(transition(mode, 'escape'), 'rest');
    assert.equal(transition(mode, 'escape', true), 'hidden');
    if (mode !== 'sneak') assert.equal(transition(mode, 'sneak'), 'sneak');
  }
  assert.equal(transition('sneak', 'sneak'), 'rest');
  assert.equal(transition('expanded', 'expand', true), 'hidden');
});
test('hover and idle never open a keyboard state', () => {
  assert.equal(transition('hidden', 'hover', true), 'peek');
  assert.equal(transition('rest', 'idle', true), 'hidden');
  assert.equal(transition('expanded', 'idle', true), 'expanded');
  assert.equal(transition('sneak', 'leave', true), 'sneak');
});
test('offline suggestions include visible configured entries only', () => {
  const config = { pins: [{ name: 'Editor', visible: true }, { name: 'Secret', visible: false }], projects: [{ name: 'FRIDAY' }] };
  assert.deepEqual(localSuggestions('proj fri', config), ['proj FRIDAY']);
  assert.deepEqual(localSuggestions('open ', config), ['open Editor']);
  assert.deepEqual(localSuggestions('open secret', config), []);
});

test('reminders require an active bounded interval, and expire exactly at its end', () => {
  const frame = { text: 'Next: DBMS', show_from: 1000, expires_at: 2000 };
  assert.equal(readReminder(frame, 999), null);
  assert.deepEqual(readReminder(frame, 1000), frame);
  assert.equal(readReminder(frame, 2000), null);
  for (const value of [{ text: 'Old server' }, { ...frame, expires_at: NaN }, { ...frame, text: '' },
    { ...frame, expires_at: Infinity }, { ...frame, expires_at: 86400002 + frame.show_from }]) {
    assert.equal(readReminder(value, 1500), null);
  }
});
