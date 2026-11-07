import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { FRAME_MS, MOODS, Mochi, motionReduced, randomDelay, readMood } from '../src/mochi.ts';

test('all eleven payloads accept the new contract, legacy expiry and bounded literal messages', () => {
  for (const mood of MOODS) {
    const state = readMood({ mood, until: 2000, sticky: false, message: '<b>' + '🌙'.repeat(70) }, 1000)!;
    assert.equal(state.mood, mood);
    assert.equal(Array.from(state.message).length, 60);
    assert.ok(state.message.startsWith('<b>'));
  }
  assert.equal(readMood({ mood: 'focused', until: null, sticky: true })?.until, null);
  assert.equal(readMood({ mood: 'happy', expires_at: 20 }, 1000)?.until, 20000);
  assert.equal(readMood({ mood: 'happy', until: 1 }, 2000)?.mood, 'idle');
  for (const value of [null, [], { mood: 'other' }, { mood: 'happy', until: NaN },
    { mood: 'happy', until: null }, { mood: 'focused', sticky: 'yes', until: null },
    { mood: 'focused', sticky: true, until: 30 }, { mood: 'happy', until: Infinity }]) assert.equal(readMood(value), null);
});

test('motion preferences are additive; idle timing and the frame cap stay in bounds', () => {
  assert.equal(motionReduced(false, false, false), false);
  assert.equal(motionReduced(true, false, false), true);
  assert.equal(motionReduced(false, true, false), true);
  assert.equal(motionReduced(undefined, false, true), true);
  assert.ok(1000 / FRAME_MS <= 30);
  assert.equal(randomDelay(3000, 6000, () => 0), 3000);
  assert.equal(randomDelay(20000, 60000, () => .999), 59960);
});

test('idle blinks, small behaviors, suspension and reduced motion use cancellable sparse timers', t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
  t.mock.method(Math, 'random', () => 0);
  t.mock.method(performance, 'now', () => Date.now());
  const styles = new Map<string, string>();
  const samples: number[] = [];
  const surface = { dataset: {} };
  const orb = { dataset: {} as Record<string, string>, setAttribute() {}, style: {
    setProperty(key: string, value: string) { samples.push(Date.now()); styles.set(key, value); },
    removeProperty(key: string) { styles.delete(key); },
  } };
  const mochi = new Mochi(surface as unknown as HTMLElement, orb as unknown as HTMLElement);
  mochi.setMood('idle'); mochi.comfort(false, false);
  t.mock.timers.tick(2999); assert.equal(orb.dataset.blink, undefined);
  t.mock.timers.tick(1); assert.equal(orb.dataset.blink, 'true');
  t.mock.timers.tick(140); assert.equal(orb.dataset.blink, undefined);
  t.mock.timers.tick(16860); assert.equal(orb.dataset.behavior, 'look');
  t.mock.timers.tick(34); assert.ok(styles.has('--mochi-look'));
  mochi.comfort(false, true);
  assert.equal(orb.dataset.behavior, undefined);
  const count = samples.length;
  t.mock.timers.tick(60000); assert.equal(samples.length, count);
  mochi.comfort(true, false); mochi.setMood('alarmed');
  t.mock.timers.tick(1000); assert.equal(samples.length, count);
  mochi.comfort(false, false);
  for (let i = 0; i < 30; i++) t.mock.timers.tick(34);
  assert.equal(samples.length - count, 30);
  mochi.close();
  t.mock.timers.tick(1000); assert.equal(samples.length - count, 30);
  mochi.setMood('dozing');
  const slow = samples.length;
  for (let i = 0; i < 4; i++) t.mock.timers.tick(250);
  assert.equal(samples.length - slow, 8); // Four slow breathing samples, two variables each.
  mochi.close();
});
