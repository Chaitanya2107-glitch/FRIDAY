import type { Config, CommandResult, Suggestion, Widget } from './types';

interface Frame { v: number; type: string; id?: string; [key: string]: unknown }
export class Connection {
  private ws?: WebSocket;
  private retry?: ReturnType<typeof setTimeout>;
  private attempts = 0;
  private generation = 0;
  private stopped = false;
  private pending = new Map<string, { resolve: (frame: Frame) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
  online = false;
  private config: Config['connection'];
  private receive: (frame: Frame) => void;
  private status: (online: boolean) => void;
  constructor(config: Config['connection'], receive: (frame: Frame) => void, status: (online: boolean) => void) {
    this.config = config; this.receive = receive; this.status = status;
  }

  start() {
    const generation = ++this.generation;
    clearTimeout(this.retry);
    this.stopped = false;
    const ws = this.ws = new WebSocket(`ws://127.0.0.1:${this.config.port}`);
    const handshake = setTimeout(() => ws.close(), 5000);
    ws.onopen = () => ws.send(JSON.stringify({ v: 1, type: 'handshake', id: 'hello', token: this.config.token }));
    ws.onmessage = event => {
      if (generation !== this.generation || typeof event.data !== 'string' || event.data.length > 65536) return;
      let frame: Frame;
      try { frame = JSON.parse(event.data) as Frame; } catch { return; }
      if (frame.v !== 1 || typeof frame.type !== 'string') { ws.close(); return; }
      if (frame.type === 'handshake' && frame.ok === true) {
        clearTimeout(handshake);
        this.online = true;
        this.attempts = 0;
        this.status(true);
      }
      if (!this.online) return;
      const pending = frame.id && this.pending.get(frame.id);
      if (pending) {
        clearTimeout(pending.timer);
        this.pending.delete(frame.id!);
        if (frame.type === 'error') pending.reject(new Error(String(frame.text ?? 'FRIDAY request failed')));
        else pending.resolve(frame);
      }
      this.receive(frame);
    };
    ws.onerror = () => ws.close();
    ws.onclose = () => {
      clearTimeout(handshake);
      if (generation !== this.generation) return;
      this.online = false;
      this.status(false);
      for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(new Error('FRIDAY disconnected. The command was not retried.')); }
      this.pending.clear();
      if (!this.stopped) this.retry = setTimeout(() => this.start(), Math.min(30000, 600 * 2 ** Math.min(6, this.attempts++)) + Math.random() * 250);
    };
  }
  stop() {
    this.stopped = true;
    ++this.generation;
    clearTimeout(this.retry);
    this.online = false;
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(new Error('Connection settings changed. The command was not retried.')); }
    this.pending.clear();
    this.ws?.close();
  }
  request(type: string, data: Record<string, unknown>, timeout = 65000): Promise<Frame> {
    if (!this.online || this.ws?.readyState !== WebSocket.OPEN) return Promise.reject(new Error('FRIDAY offline'));
    const id = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('FRIDAY took too long. The command was not retried.')); }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.ws!.send(JSON.stringify({ v: 1, type, id, ...data }));
    });
  }
  async command(text: string) { return await this.request('command', { text }) as unknown as CommandResult; }
  async suggestions(text: string): Promise<Suggestion[]> {
    const frame = await this.request('suggestions', { text }, 3000);
    if (!Array.isArray(frame.items)) return [];
    return frame.items.filter((i): i is Suggestion => typeof i === 'object' && i !== null && typeof i.text === 'string').slice(0, 6);
  }
  async widget(plugin: string): Promise<Widget> { return (await this.request('plugin_widget', { plugin }, 5000)).widget as Widget; }
}
