import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { replyDuration } from '../src/reply-state.ts';

test('brief acknowledgements last five seconds, detailed replies and work last thirty', () => {
  assert.equal(replyDuration({ text: 'Opened Calculator', kind: 'reply' }), 5000);
  for (const reply of [
    { text: 'a'.repeat(161), kind: 'reply' }, { text: 'One\nTwo', kind: 'reply' },
    { text: 'Saved report', kind: 'work' }, { text: 'Drink water', kind: 'reminder' },
    { text: 'Could not save', kind: 'reply', bad: true },
  ] as const) assert.equal(replyDuration(reply), 30000);
  assert.equal(replyDuration({ text: 'Confirm?', kind: 'question', awaiting: true }), 0);
  assert.equal(replyDuration({ text: 'Working…', kind: 'work', pending: true }), 0);
});
