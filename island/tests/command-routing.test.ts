import test from 'node:test';
import assert from 'node:assert/strict';
import { nativeCommand } from '../src/command-routing.ts';
import { Dictation } from '../src/dictation.ts';

test('integrated natural commands stay canonical; explicit apps and offline launches remain available', () => {
  for (const text of ['open phone link', 'open college schedules', 'open my notes', 'settings friday']) assert.equal(nativeCommand(text, true, false), false);
  assert.equal(nativeCommand('open Calculator', true, true), true);
  assert.equal(nativeCommand('open Calculator', false, false), true);
  assert.equal(nativeCommand('settings', true, false), true);
  assert.equal(nativeCommand('proj Friday', true, false), true);
});

test('dictation auto-submits pasted speech once; cancellation prevents delayed execution', async context => {
  context.mock.timers.enable({ apis: ['setTimeout'] });
  const controls: string[] = [], submitted: string[] = [];
  const dictation = new Dictation({ control: async action => { controls.push(action); },
    prepare: async () => {}, value: () => 'fixture speech', submit: async text => { submitted.push(text); }, message: () => {} });
  await dictation.toggle(); dictation.input(true); context.mock.timers.tick(400);
  assert.deepEqual(submitted, ['fixture speech']);
  await dictation.toggle(); dictation.input(true); dictation.input(false); context.mock.timers.tick(500);
  assert.deepEqual(submitted, ['fixture speech']);
  assert.deepEqual(controls, ['toggle', 'toggle', 'cancel']);
});

test('leaving during Handy startup prevents or cancels the pending toggle', async () => {
  for (const delay of ['prepare', 'toggle'] as const) {
    const controls: string[] = [];
    let resume!: () => void;
    const pending = new Promise<void>(resolve => { resume = resolve; });
    const dictation = new Dictation({
      prepare: async () => { if (delay === 'prepare') await pending; },
      control: async action => { controls.push(action); if (delay === action) await pending; },
      value: () => '', submit: async () => {}, message: () => {},
    });
    const starting = dictation.toggle();
    await Promise.resolve();
    dictation.cancel(); resume(); await starting;
    assert.deepEqual(controls, delay === 'prepare' ? [] : ['toggle', 'cancel']);
  }
});
