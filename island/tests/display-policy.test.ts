import test from 'node:test';
import assert from 'node:assert/strict';
import { displayMode, restoredMode } from '../src/display-policy.ts';

test('gaming wins over every requested surface and restores without keyboard focus', () => {
  for (const mode of ['rest', 'peek', 'expanded', 'sneak', 'hidden'] as const) {
    assert.equal(displayMode(mode, true), 'hidden');
    assert.equal(displayMode(mode, false), mode);
  }
  assert.equal(restoredMode('always', false), 'rest');
  assert.equal(restoredMode('auto-hide', false), 'rest');
  assert.equal(restoredMode('hover', false), 'hidden');
  assert.equal(restoredMode('always', true), 'hidden');
});
