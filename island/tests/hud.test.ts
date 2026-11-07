import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { HudPoller, remaining, saving, type HudSettings } from '../src/hud-model.ts';

test('automatic saver requires unplugged battery strictly below configured threshold', () => {
  const settings = { saver: false, auto_saver: true, battery_threshold: 30 } as HudSettings;
  const stats = (percent: number, plugged = false) => ({ battery: { percent, plugged, charging: plugged } }) as Parameters<typeof saving>[1];
  assert.equal(saving(settings, stats(29)), true); assert.equal(saving(settings, stats(30)), false);
  assert.equal(saving(settings, stats(10, true)), false); assert.equal(saving(settings, null), false);
  assert.equal(saving({ ...settings, saver: true }, null), true);
  assert.equal(saving({ ...settings, auto_saver: false }, stats(1)), false);
});

test('focus uses wall-clock deadlines and preserves paused remaining time', () => {
  const focus = { session_id: 'a', duration_s: 1500, ends_at: 2000, remaining_s: null };
  assert.equal(remaining(focus, 1900), 100); assert.equal(remaining(focus, 2100), 0);
  assert.equal(remaining({ ...focus, ends_at: null, remaining_s: 80 }, 9000), 80);
});

test('hidden HUD aborts requests, fences late responses, and starts no subsequent polls', async () => {
  let complete: (value: unknown) => void = () => {}; let signal: AbortSignal; let calls = 0, renders = 0;
  const poller = new HudPoller(value => { signal = value; calls++; return new Promise(resolve => { complete = resolve; }); },
    () => { renders++; return 5000; });
  poller.show(); assert.equal(calls, 1); poller.stop(); assert.equal(signal!.aborted, true);
  complete({}); await new Promise(resolve => setTimeout(resolve, 35));
  assert.equal(calls, 1); assert.equal(renders, 0);
});
