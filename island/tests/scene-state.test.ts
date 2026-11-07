import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { SceneState } from '../src/scene-state.ts';
import { resolveSlash, slashSuggestions } from '../src/slash-commands.ts';

test('focus and scenes use full-backend commands; note keeps its real existing route', () => {
  assert.equal(resolveSlash('/focus').text, 'focus');
  assert.equal(resolveSlash('/focus 25').text, 'focus 25');
  assert.equal(resolveSlash('/pomodoro').text, 'pomodoro');
  assert.equal(resolveSlash('/scene study').text, 'start study scene');
  assert.equal(resolveSlash('/scenes').text, 'list scenes');
  assert.equal(resolveSlash('/note Keep this').text, 'note Keep this');
  assert.ok(slashSuggestions('/focus').length);
  assert.throws(() => resolveSlash('/focus 25', [], 'standalone'), /full FRIDAY backend/);
});

test('active scene survives initial status, changes live and ignores stale end events', () => {
  const state = new SceneState();
  state.status({ active: 'study', scene_id: 'one' });
  assert.equal(state.name, 'study');
  state.event({ topic: 'scene.started', payload: { name: 'game', scene_id: 'two' } });
  state.event({ topic: 'scene.ended', payload: { name: 'study', scene_id: 'one' } });
  assert.equal(state.name, 'game');
  state.event({ topic: 'scene.state', payload: { name: null, scene_id: null } });
  assert.equal(state.name, '');
  state.event({ topic: 'scene.started', payload: { name: '<b>literal</b>', scene_id: 'three' } });
  assert.equal(state.name, '<b>literal</b>'); // Caller uses textContent, never HTML.
  state.reset(); assert.equal(state.id, '');
});
