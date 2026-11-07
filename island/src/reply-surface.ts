import './reply.css';
import { icon } from './icons';
import { element as el } from './state';
import { replyDuration, type CapsuleReply } from './reply-state';
import { pluginCard } from './plugin-card';
import { searchCardBody } from './search-card';
import type { CommandResult, FridayState, Mode, PillSnippet } from './types';

/** Live replies share the resting capsule; history stays in the FRIDAY tab. */
export class ReplySurface {
  readonly node = el('div', 'capsule-reply');
  private content = el('div', 'capsule-reply-content');
  private title = el('strong', 'capsule-reply-title');
  private text = el('p', 'capsule-reply-text');
  private actions = el('div', 'capsule-reply-actions');
  private pending = el('small', 'capsule-reply-pending', 'Type or speak your answer.');
  private queue: CapsuleReply[] = [];
  private timer?: ReturnType<typeof setTimeout>;
  private started = 0;
  private remaining = 0;
  private shown = false;
  private hovering = false;
  private seen = new Set<string>();
  private searchGeneration = 0;

  constructor(private surface: HTMLElement, private host: {
    mode: () => Mode; sneak: () => boolean; available: () => boolean;
    reveal: () => Promise<void>; restore: () => Promise<void>; changed: () => void;
    action: (token: string) => Promise<CommandResult>;
    pluginAction: (owner: string, id: string, payload: Record<string, unknown>) => Promise<CommandResult>;
    pluginGet: (path: string) => Promise<Record<string, unknown>>;
  }) {
    this.content.append(this.title, this.text, this.pending, this.actions);
    this.text.setAttribute('role', 'status'); this.text.setAttribute('aria-live', 'polite');
    this.text.tabIndex = 0;
    const close = el('button', 'capsule-reply-dismiss'); close.append(icon('close'));
    close.title = 'Acknowledge and dismiss'; close.setAttribute('aria-label', 'Acknowledge reply');
    close.onpointerdown = event => event.preventDefault(); close.onclick = () => this.dismiss();
    this.node.append(this.content, close);
    this.node.onpointerenter = () => { this.hovering = true; this.pause(); };
    this.node.onpointerleave = () => { this.hovering = false; this.resume(); };
    this.node.addEventListener('focusin', () => this.pause());
    this.node.addEventListener('focusout', () => queueMicrotask(() => this.resume()));
  }

  get visible() { return this.shown; }

  begin() { this.offer({ text: 'Working…', kind: 'work', pending: true }, true); }

  finish() {
    if (!this.queue.some(reply => reply.pending)) { if (!this.queue.length) this.reveal(); return; }
    this.pause(); this.queue = this.queue.filter(reply => !reply.pending); this.shown = false; this.paint(); this.reveal();
  }

  flush() {
    if (this.queue.length && !this.host.sneak() && this.host.mode() === 'hidden' && this.host.available()) void this.host.reveal();
  }

  offer(reply: CapsuleReply, priority = false) {
    if (this.host.sneak() || !reply.text.trim()) return;
    const item = { ...reply, text: reply.text.slice(0, 32000) };
    if (reply.pluginId) this.queue = this.queue.filter(row => row.pluginId !== reply.pluginId);
    if (priority) this.queue = [item, ...this.queue.filter((row, index) => row.kind === 'reminder' || (index > 0 && !row.pending))].slice(0, 8);
    else if (this.queue.length < 8) this.queue.push(item);
    else return;
    if (priority || this.queue.length === 1) { this.pause(); this.shown = false; this.paint(); }
    this.reveal();
    if (item.ttlMs !== undefined) setTimeout(() => {
      if (!this.queue.includes(item)) return;
      this.pause(); this.queue = this.queue.filter(row => row !== item); this.shown = false; this.paint(); this.reveal();
    }, item.ttlMs);
  }

  pluginEvent(event: Record<string, unknown>) {
    if (!['smart_clipboard', 'semantic_search', 'scenes'].includes(String(event.plugin_id))) return false;
    const card = pluginCard(event);
    if (!card || this.host.mode() === 'expanded') return false;
    const reply: CapsuleReply = { text: card.text, title: card.title, kind: 'reminder', pluginId: card.owner,
      private: card.owner === 'semantic_search' || card.owner === 'scenes',
      awaiting: card.owner === 'scenes' && card.actions.length > 0,
      ttlMs: card.ttlMs, swatch: card.swatch,
      pluginActions: card.actions.map(action => ({ label: action.label,
        run: () => this.host.pluginAction(card.owner, action.id, action.payload) })) };
    this.offer(reply, true);
    if (card.owner === 'semantic_search') {
      const generation = ++this.searchGeneration;
      void searchCardBody(card.owner, event.payload as Record<string, unknown>, path => this.host.pluginGet(path)).then(text => {
        if (text !== undefined && generation === this.searchGeneration && this.queue.some(row => row.pluginId === card.owner))
          this.offer({ ...reply, text }, true);
      }).catch(() => { /* Filename-only chips remain available after plugin reload. */ });
    }
    return true;
  }

  result(reply: CommandResult) {
    if (reply.awaiting_reply && this.queue.some(item => item.pluginId === 'scenes' && item.awaiting)) {
      this.reveal(); return; // Keep the visible Yes/No card ahead of its duplicate chat text.
    }
    this.queue = this.queue.filter(item => !item.awaiting);
    this.offer({ text: reply.text, kind: reply.awaiting_reply ? 'question' : reply.automation_job || reply.action_success === true ? 'work' : 'reply',
      private: reply.private, bad: !reply.ok, awaiting: reply.awaiting_reply }, true);
  }

  event(event: FridayState['events'][number]) {
    if (event.kind === 'reply_state') {
      if (!event.awaiting_reply) this.resolve();
      return;
    }
    if (!['response', 'question', 'notification', 'work'].includes(event.kind)) return;
    this.offer({ text: event.text, title: event.title,
      kind: event.kind === 'notification' ? 'reminder' : event.kind === 'question' ? 'question' : event.kind === 'work' ? 'work' : 'reply',
      awaiting: event.kind === 'question' || event.awaiting_reply, buttons: event.buttons }, event.kind !== 'notification' && !this.queue.some(reply => reply.pending));
  }

  snippet(reminder: PillSnippet | null) {
    if (!reminder || this.host.sneak()) return;
    const key = JSON.stringify(reminder);
    if (this.seen.has(key)) return;
    this.seen.add(key);
    if (this.seen.size > 40) this.seen.delete(this.seen.values().next().value!);
    this.offer({ text: reminder.text, kind: 'reminder', title: 'Reminder' });
  }

  sync() {
    const mode = this.host.mode();
    if (this.host.sneak()) { this.clear(); return; }
    if (mode !== 'rest' && this.queue.some(reply => reply.private)) {
      this.pause(); this.queue = this.queue.filter(reply => !reply.private); this.shown = false; this.paint();
    }
    const visible = mode === 'rest' && !!this.queue.length;
    this.surface.classList.toggle('replying', visible);
    if (visible === this.shown) return;
    this.pause(); this.shown = visible;
    if (visible) this.resume();
    this.host.changed();
  }

  dismiss() {
    this.pause(); this.queue.shift(); this.shown = false; this.paint(); this.reveal();
  }

  resolve() {
    if (!this.queue.some(reply => reply.awaiting)) return;
    this.pause(); this.queue = this.queue.filter(reply => !reply.awaiting); this.shown = false; this.paint(); this.reveal();
  }

  resolvePrivate() {
    if (!this.queue.some(reply => reply.private)) return;
    this.pause(); this.queue = this.queue.filter(reply => !reply.private); this.shown = false; this.paint(); this.reveal();
  }

  clear() {
    this.pause(); this.queue = []; this.shown = false; this.paint();
    this.surface.classList.remove('replying'); this.host.changed();
  }

  private reveal() {
    if (this.queue.length && this.host.available()) void this.host.reveal();
    else if (!this.queue.length && this.host.mode() === 'rest') void this.host.restore();
    this.sync();
  }

  private paint() {
    const reply = this.queue[0];
    this.title.textContent = reply ? reply.pending ? 'FRIDAY is working' : reply.private ? 'Private reply' : reply.kind === 'reminder' ? reply.title || 'Reminder'
      : reply.kind === 'work' ? 'Work result' : reply.awaiting ? 'FRIDAY needs your reply' : 'FRIDAY' : '';
    this.text.textContent = reply?.text ?? ''; this.text.scrollTop = 0;
    this.pending.hidden = !reply?.awaiting;
    this.node.classList.toggle('bad', !!reply?.bad);
    this.surface.classList.toggle('reply-long', !!reply && replyDuration(reply) !== 5000);
    this.actions.replaceChildren();
    if (reply?.swatch) {
      const swatch = el('span', 'clipboard-swatch'); swatch.style.backgroundColor = reply.swatch;
      swatch.setAttribute('role', 'img'); swatch.setAttribute('aria-label', `Color ${reply.swatch}`);
      this.actions.append(swatch);
    }
    for (const action of reply?.pluginActions ?? []) {
      const button = el('button', '', action.label); button.onpointerdown = event => event.preventDefault();
      button.onclick = () => {
        button.disabled = true;
        void action.run().then(result => {
          if (result.ok) {
            if (this.queue[0] === reply) this.dismiss();
            else this.queue = this.queue.filter(row => row !== reply);
          } else { button.disabled = false; this.offer({ kind: 'reply', text: result.text, bad: true }); }
        }).catch(() => { button.disabled = false; });
      };
      this.actions.append(button);
    }
    for (const pair of Array.isArray(reply?.buttons) ? reply.buttons.slice(0, 6) : []) {
      if (!Array.isArray(pair) || typeof pair[0] !== 'string' || typeof pair[1] !== 'string' || !pair[1].startsWith('friday://')) continue;
      const button = el('button', '', pair[0]);
      button.onpointerdown = event => event.preventDefault();
      button.onclick = () => {
        button.disabled = true;
        void this.host.action(pair[1]).then(result => {
          if (result.ok) {
            if (this.queue[0] === reply) this.dismiss();
            else this.queue = this.queue.filter(item => item !== reply);
          }
          this.offer({ kind: 'reply', text: result.text, bad: !result.ok });
        }).catch(error => this.offer({ kind: 'reply', text: String(error), bad: true }));
      };
      this.actions.append(button);
    }
    this.remaining = reply ? replyDuration(reply) : 0;
  }

  private pause() {
    clearTimeout(this.timer); this.timer = undefined;
    if (this.started) this.remaining = Math.max(1, this.remaining - (Date.now() - this.started));
    this.started = 0;
  }

  private resume() {
    if (!this.shown || this.timer || !this.remaining || this.hovering || this.node.contains(document.activeElement)) return;
    this.started = Date.now(); this.timer = setTimeout(() => this.dismiss(), this.remaining);
  }
}
