import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { Conversation, readReply } from '../src/conversation.ts';

test('private turn never enters transcript and closes without affecting prior history', () => {
  const state = new Conversation();
  state.accept('hello', { ok: true, text: 'Hi' });
  state.accept('private prompt', { ok: true, text: 'Private text', private: true, awaiting_reply: true });
  assert.equal(state.turns.length, 2);
  assert(!JSON.stringify(state.turns).includes('private'));
  assert.equal(state.privateReply, 'Private text');
  state.event('Reminder');
  assert.equal(state.privateReply, 'Private text'); assert.equal(state.awaiting, true);
  state.close(); assert.equal(state.privateReply, '');
});

test('reply metadata survives validation and does not invent approval actions', () => {
  const reply = readReply({ ok: false, text: 'Which date?', awaiting_reply: true, private: true,
    keyboard_token: 'token', automation_job: 'job', action_success: false });
  assert.equal(reply.awaiting_reply, true); assert.equal(reply.keyboard_token, 'token');
  assert.equal(reply.private, true); assert.equal(reply.action_success, false);
  assert.throws(() => readReply({ ok: 'false', text: 'wrong' }));
});

test('history and new replies retain only three recent exchanges', () => {
  const state = new Conversation();
  const items = Array.from({ length: 12 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: `turn ${i}` }));
  state.history(items);
  assert.deepEqual(state.turns, items.slice(-6));
  state.accept('new question', { ok: true, text: 'New answer' });
  assert.equal(state.turns.length, 6);
  assert.equal(state.turns[0].content, 'turn 8');
  for (let i = 0; i < 5; i++) state.event(`Event ${i}`);
  assert.equal(state.turns.length, 3);
  assert.equal(state.turns[0].content, 'Event 2');
});
