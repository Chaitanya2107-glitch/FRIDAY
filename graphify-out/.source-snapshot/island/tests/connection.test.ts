import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { Connection } from '../src/connection.ts';

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 1;
  sent: string[] = [];
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onerror?: () => void;
  onclose?: () => void;
  constructor(_url: string) { Socket.instances.push(this); }
  send(text: string) { this.sent.push(text); }
  close() { this.readyState = 3; }
  receive(frame: unknown) { this.onmessage?.({ data: JSON.stringify(frame) }); }
}

test('replaced socket cannot change status or replay a command', async () => {
  const original = globalThis.WebSocket;
  globalThis.WebSocket = Socket as unknown as typeof WebSocket;
  const states: boolean[] = [];
  const connection = new Connection({ port: 17321, token: '0'.repeat(64) }, () => {}, value => states.push(value));
  try {
    connection.start();
    const first = Socket.instances.at(-1)!;
    first.onopen!(); first.receive({ v: 1, type: 'handshake', ok: true });
    const pending = assert.rejects(connection.command('next'), /not retried/);
    connection.stop();
    await pending;
    connection.start();
    const second = Socket.instances.at(-1)!;
    second.onopen!(); second.receive({ v: 1, type: 'handshake', ok: true });
    first.onclose!();
    assert.equal(connection.online, true);
    assert.deepEqual(states, [true, true]);
    assert.equal(second.sent.length, 1, 'Only handshake, no replay');
  } finally { connection.stop(); globalThis.WebSocket = original; }
});

test('disconnect settles pending request and malformed frames do not authenticate', async () => {
  const original = globalThis.WebSocket;
  globalThis.WebSocket = Socket as unknown as typeof WebSocket;
  const connection = new Connection({ port: 17321, token: '0'.repeat(64) }, () => {}, () => {});
  try {
    connection.start();
    const socket = Socket.instances.at(-1)!;
    socket.onopen!(); socket.onmessage!({ data: '{broken' });
    assert.equal(connection.online, false);
    socket.receive({ v: 1, type: 'handshake', ok: true });
    const pending = assert.rejects(connection.command('next'), /not retried/);
    socket.onclose!();
    await pending;
    assert.equal(connection.online, false);
  } finally { connection.stop(); globalThis.WebSocket = original; }
});

test('widget mutation rejects malformed acknowledgements without claiming success', async () => {
  const original = globalThis.WebSocket;
  globalThis.WebSocket = Socket as unknown as typeof WebSocket;
  const connection = new Connection({ port: 17321, token: '0'.repeat(64) }, () => {}, () => {});
  try {
    connection.start(); const socket = Socket.instances.at(-1)!;
    socket.onopen!(); socket.receive({ v: 1, type: 'handshake', ok: true });
    const response = connection.pluginAction('todo', { action: 'add', value: 'Keep draft' });
    const request = JSON.parse(socket.sent.at(-1)!);
    socket.receive({ v: 1, type: 'command_result', id: request.id, ok: 'false', text: 'Malformed' });
    await assert.rejects(response, /verify whether it was saved/);
  } finally { connection.stop(); globalThis.WebSocket = original; }
});
