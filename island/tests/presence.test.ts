import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { presenceLabels, presenceText, readPresence } from '../src/presence.ts';

const observation = { state: 'at_home', reason: 'Home signal is recent.', confidence: .84, since: 1800000000, data_available: true };

test('presence renders every finite state as an estimate without exposing raw place or device', () => {
  for (const state of Object.keys(presenceLabels)) {
    const parsed = readPresence({ ...observation, state, place: 'Private place', device: 'phone-key' });
    assert.equal(parsed?.state, state);
    assert.equal('place' in parsed!, false);
    assert.equal('device' in parsed!, false);
  }
  assert.deepEqual(presenceText(observation), { label: 'At home', confidence: '84% confidence',
    detail: 'Home signal is recent.', available: true });
  assert.equal(presenceText(observation, true).label, 'Last known · At home');
  assert.match(presenceText(observation, true).detail, /^Last known estimate\./);
});

test('missing, unavailable and malformed signals never imply away or another location', () => {
  for (const value of [undefined, null, [], {}, { ...observation, state: 'somewhere' },
    { ...observation, state: '__proto__' }, { ...observation, data_available: false },
    { ...observation, confidence: -1 }, { ...observation, confidence: Infinity },
    { ...observation, confidence: 1.01 }, { ...observation, since: NaN },
    { ...observation, reason: 'x'.repeat(401) }]) {
    assert.equal(readPresence(value), undefined);
    assert.equal(presenceText(value).label, 'Presence unavailable');
  }
});

test('stream projections remain compatible and untrusted text stays literal', () => {
  const { data_available: _, ...stream } = observation;
  assert.equal(presenceText(stream).available, true);
  assert.equal(presenceText({ ...stream, reason: '<img src=x onerror=alert(1)>\nnext' }).detail,
    '<img src=x onerror=alert(1)> next');
});
