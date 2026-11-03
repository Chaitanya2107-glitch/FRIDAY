import type { CommandResult } from './types.ts';

export interface Turn { role: string; content: string }
export function readReply(frame: Record<string, unknown>): CommandResult {
  if (typeof frame.text !== 'string' || frame.text.length > 32000 || typeof frame.ok !== 'boolean')
    throw Error('Invalid FRIDAY reply. Check its state before repeating an action.');
  const result: CommandResult = { text: frame.text, ok: frame.ok };
  for (const key of ['private', 'awaiting_reply'] as const) if (typeof frame[key] === 'boolean') result[key] = frame[key];
  for (const key of ['provider', 'model', 'keyboard_token', 'automation_job'] as const)
    if (typeof frame[key] === 'string' && (frame[key] as string).length <= 128) result[key] = frame[key] as string;
  if (typeof frame.action_success === 'boolean' || frame.action_success === null) result.action_success = frame.action_success;
  if (frame.action && typeof frame.action === 'object') result.action = frame.action as CommandResult['action'];
  return result;
}

export class Conversation {
  turns: Turn[] = [];
  privateReply = '';
  awaiting = false;
  accept(prompt: string, reply: CommandResult) {
    this.privateReply = '';
    this.awaiting = reply.awaiting_reply === true;
    if (reply.private) { this.privateReply = reply.text; return; }
    if (prompt) this.turns.push({ role: 'user', content: prompt });
    this.turns.push({ role: 'assistant', content: reply.text });
    this.trim();
  }
  close() { this.privateReply = ''; }
  event(text: string, question = false) {
    this.turns.push({ role: 'assistant', content: text }); this.trim();
    if (question) this.awaiting = true;
  }
  clear() { this.turns = []; this.awaiting = false; this.close(); }
  history(items: unknown) {
    if (!Array.isArray(items)) return;
    this.turns = items.filter((item): item is Turn => item && ['user', 'assistant'].includes(item.role)
      && typeof item.content === 'string').slice(-6).map(item => ({ role: item.role, content: item.content.slice(0, 32000) }));
    this.trim();
  }
  private trim() {
    let replies = 0;
    for (let i = this.turns.length - 1; i >= 0; i--) {
      if (this.turns[i].role === 'assistant' && ++replies > 3) { this.turns = this.turns.slice(i + 1); break; }
    }
    this.turns = this.turns.slice(-6);
  }
}
