import { Conversation } from './conversation';
import { element as el } from './state';
import type { Connection } from './connection';
import type { CommandResult, FridayState } from './types';
import { call } from './native';

export class FridayPanel {
  readonly conversation = new Conversation();
  state?: FridayState;
  private root = el('section', 'friday-panel');
  private status = el('p', 'friday-status', 'Connecting to FRIDAY…');
  private detail = el('p', 'muted');
  private log = el('div', 'friday-transcript');
  private notices = el('div', 'friday-notices');
  private automation = el('div', 'friday-automation');
  private controls = new Map<string, HTMLButtonElement>();
  private provider = el('select');
  private epoch = '';
  private cursor = 0;
  private displayed = new Set<string>();
  private online = false;
  private historyLoaded = false;
  private painted = '';
  private automationSignature?: string;

  constructor(private connection: () => Connection, private submit: (text: string) => Promise<void>,
              private message: (text: string, bad?: boolean) => void,
              private reveal: (event: FridayState['events'][number]) => void, private prepare: () => Promise<void>) {
    this.log.setAttribute('role', 'log'); this.log.setAttribute('aria-label', 'FRIDAY conversation');
    this.log.setAttribute('aria-live', 'polite');
    this.root.append(this.status, this.detail);
    const controls = el('div', 'friday-controls');
    for (const [action, label] of [['listen', 'Listen'], ['voice_stop', 'Stop listening'], ['speech_stop', 'Stop speaking'], ['automation_stop', 'Stop tasks'],
      ['wake', 'Hey Friday'], ['conversation', 'Conversation'], ['speech', 'Spoken replies'], ['speak_typed', 'Speak typed replies']] as const) {
      const button = this.button(label, () => this.action(action)); controls.append(button); this.controls.set(action, button);
    }
    this.provider.setAttribute('aria-label', 'FRIDAY provider');
    for (const name of ['', 'ollama', 'openrouter', 'anthropic', 'openai']) {
      const option = el('option', '', name || 'Default provider'); option.value = name; this.provider.append(option);
    }
    this.provider.onchange = () => void this.action('provider', this.provider.value);
    controls.append(this.provider); this.root.append(controls, this.log, this.automation, this.notices);
    const features = el('div', 'friday-features');
    for (const [action, label] of [['college', 'College schedules'], ['productivity', 'Habits & To-do'],
      ['customization', 'Customize FRIDAY'], ['controls', 'All controls'], ['body', 'Show / hide robot']] as const)
      features.append(this.button(label, () => action === 'controls' ? call('open_controls') : this.action(action)));
    for (const [text, label] of [['read my notes', 'Notes'], ['list reminders', 'Reminders'], ['show deadlines', 'Deadlines'],
      ['screen awareness status', 'Screen awareness'], ['browser status', 'Browser & research'], ['phone status', 'Phone'],
      ['brain status', 'Memory & brain'], ['what mode am I in', 'Current mode']] as const)
      features.append(this.button(label, () => this.submit(text)));
    features.append(this.button('Clear display', async () => { this.conversation.clear(); this.paintConversation(); }));
    this.root.append(features);
    const lifecycle = el('div', 'friday-controls');
    const start = el('button', 'text-button', 'Start FRIDAY');
    start.onclick = () => void call('start_friday').then(() => this.message('Starting FRIDAY…')).catch(error => this.message(String(error), true));
    lifecycle.append(start);
    for (const [action, label] of [['restart', 'Restart FRIDAY'], ['stop', 'Stop FRIDAY'], ['quit', 'Quit FRIDAY']] as const)
      lifecycle.append(this.button(label, async () => {
        if (window.confirm(`${label}?`)) {
          if (action === 'quit') await call('quit');
          else if (!this.online && action === 'restart') await call('start_friday');
          else await this.action(action);
        }
      }));
    this.root.append(lifecycle);
  }
  private button(label: string, run: () => Promise<unknown>) {
    const button = el('button', 'text-button', label); button.type = 'button';
    button.onclick = () => { button.disabled = true; void run().catch(error => this.message(String(error), true)).finally(() => { button.disabled = false; this.paintState(); }); };
    return button;
  }
  mount(host: HTMLElement) { host.append(this.root); this.paintConversation(); this.paintState(); }
  close() { this.conversation.close(); this.paintConversation(); }
  connected(online: boolean) {
    this.online = online;
    if (!online) { this.state = undefined; this.automationSignature = undefined; this.conversation.awaiting = false; this.close(); }
    this.paintState();
  }
  receive(frame: Record<string, unknown>): boolean {
    if (frame.type !== 'runtime_state' || frame.backend !== true || typeof frame.epoch !== 'string'
      || !frame.body || !frame.desktop || !frame.system || !Array.isArray(frame.events)) return false;
    const state = frame as unknown as FridayState;
    if (this.epoch !== state.epoch) { this.cursor = 0; this.displayed.clear(); this.historyLoaded = false; this.automationSignature = undefined; this.epoch = state.epoch; }
    this.state = state;
    for (const event of state.events) {
      if (typeof event.id !== 'number' || typeof event.text !== 'string' || event.id <= this.cursor) continue;
      this.cursor = event.id;
      const key = `${state.epoch}:${event.id}`;
      if (this.displayed.has(key)) continue;
      this.displayed.add(key);
      if (this.displayed.size > 160) this.displayed.delete(this.displayed.values().next().value!);
      if (event.kind === 'reply_state') {
        this.conversation.awaiting = event.awaiting_reply === true;
        this.reveal(event);
        continue;
      }
      if (!event.transient && event.kind !== 'notification') {
        if (this.conversation.turns.at(-1)?.content !== event.text) this.conversation.event(event.text, event.kind === 'question');
        else if (event.kind === 'question') this.conversation.awaiting = true;
      }
      if (event.kind === 'notification') this.notice(event);
      this.reveal(event);
    }
    const task = state.automation;
    const signature = JSON.stringify([task.job_id, task.active, task.state, task.response, task.awaiting_reply]);
    if (this.automationSignature !== undefined && signature !== this.automationSignature && task.response
        && task.state !== 'idle' && (!task.active || task.awaiting_reply))
      this.reveal({ id: 0, kind: 'work', text: task.response, title: 'Browser / research', at: Date.now() / 1000,
        buttons: [], awaiting_reply: task.awaiting_reply });
    this.automationSignature = signature;
    this.cursor = Math.max(this.cursor, state.last);
    if (!this.historyLoaded && !this.conversation.turns.length) {
      this.historyLoaded = true;
      void this.connection().request('history', {}, 5000).then(frame => {
        if (!this.conversation.turns.length) this.conversation.history(frame.items);
        this.paintConversation();
      }).catch(() => {});
    }
    this.paintState(); this.paintConversation(); return true;
  }
  accept(prompt: string, reply: CommandResult) { this.conversation.accept(prompt, reply); this.paintConversation(); }
  private paintConversation() {
    const signature = JSON.stringify([this.conversation.turns, this.conversation.privateReply, this.conversation.awaiting]);
    if (this.painted === signature) return;
    this.painted = signature;
    this.log.replaceChildren();
    for (const turn of this.conversation.turns) {
      const row = el('div', `friday-turn ${turn.role}`);
      row.append(el('strong', '', turn.role === 'user' ? 'You' : 'FRIDAY'), el('p', '', turn.content)); this.log.append(row);
    }
    if (this.conversation.privateReply) {
      const row = el('div', 'friday-turn private'); row.append(el('strong', '', 'Private · clears when closed'), el('p', '', this.conversation.privateReply)); this.log.append(row);
    }
    if (this.conversation.awaiting) this.log.append(el('p', 'friday-pending', 'FRIDAY is waiting for your reply. Type or speak your answer.'));
    if (!this.log.childElementCount) this.log.append(el('p', 'muted', 'Ask FRIDAY or run any of your usual commands.'));
    this.log.scrollTop = this.log.scrollHeight;
  }
  private paintState() {
    const state = this.state;
    this.status.textContent = !this.online ? 'FRIDAY disconnected' : !state ? 'Bridge connected · checking FRIDAY…'
      : state.body.listening ? 'Listening' : state.body.speaking ? 'Speaking' : state.body.thinking ? 'Thinking' : 'FRIDAY ready';
    this.detail.textContent = state ? `${state.system.mode.name ?? 'Mode unavailable'} · ${state.desktop.provider || state.provider} · Screen: ${state.system.screen_watch.state ?? 'off'}${state.desktop.connected ? '' : ' · Desktop controls unavailable'}` : '';
    for (const [action, button] of this.controls) {
      const active = action === 'listen' ? state?.body.listening : action === 'wake' ? state?.desktop.wake
        : action === 'conversation' ? state?.desktop.conversation : action === 'speech' ? state?.desktop.speak
        : action === 'speak_typed' ? state?.desktop.speak_typed : false;
      button.setAttribute('aria-pressed', String(!!active));
      button.disabled = !this.online || (!action.endsWith('_stop') && !state?.desktop.connected);
    }
    if (document.activeElement !== this.provider) this.provider.value = state?.desktop.provider ?? '';
    this.provider.disabled = !state?.desktop.connected;
    const progress = state?.automation;
    const text = progress?.state && progress.state !== 'idle' ? progress.response ?? progress.state : '';
    if (this.automation.dataset.text !== text) {
      this.automation.dataset.text = text; this.automation.replaceChildren();
      if (text) {
        this.automation.append(el('strong', '', 'Browser / research task'), el('p', '', text));
      }
    }
  }
  private async action(action: string, value = '') {
    if (['listen', 'wake', 'conversation'].includes(action)) await this.prepare();
    const result = await this.connection().request('runtime_action', { action, value }, 10000);
    if (result.ok === false) throw Error(String(result.text));
    if (action === 'automation_stop') { this.conversation.awaiting = false; this.paintConversation(); }
    this.message(String(result.text ?? 'Requested'));
  }
  private notice(event: FridayState['events'][number]) {
    if ([...this.notices.children].some(card => (card as HTMLElement).dataset.text === event.text
        && Math.abs(Number((card as HTMLElement).dataset.at) - event.at) < 3)) return;
    const card = el('div', 'friday-notice'); card.append(el('strong', '', event.title || 'FRIDAY'), el('p', '', event.text));
    card.dataset.text = event.text; card.dataset.at = String(event.at);
    for (const pair of Array.isArray(event.buttons) ? event.buttons : []) {
      if (!Array.isArray(pair) || typeof pair[0] !== 'string' || typeof pair[1] !== 'string' || !pair[1].startsWith('friday://')) continue;
      const action = this.button(pair[0], async () => { await this.action('notification', pair[1]); card.remove(); }); card.append(action);
    }
    card.append(this.button('Dismiss', async () => card.remove())); this.notices.prepend(card);
    while (this.notices.childElementCount > 3) this.notices.lastElementChild?.remove();
  }
}
