/** Authenticated fetch streaming: tokens never enter EventSource URLs or logs. */
export class PluginEvents {
  private abort?: AbortController;
  private retry?: ReturnType<typeof setTimeout>;
  private generation = 0;
  private stopped = true;
  private port: number;
  private token: string;
  private receive: (event: Record<string, unknown>) => void;
  constructor(port: number, token: string, receive: (event: Record<string, unknown>) => void) {
    this.port = port; this.token = token; this.receive = receive;
  }

  start() {
    this.stop(); this.stopped = false;
    const generation = ++this.generation;
    const run = async () => {
      this.abort = new AbortController();
      try {
        const response = await fetch(`http://127.0.0.1:${this.port}/api/events`, {
          headers: { 'X-Friday-Token': this.token }, signal: this.abort.signal, credentials: 'omit', cache: 'no-store',
        });
        if (!response.ok || !response.body) throw new Error('Plugin events unavailable');
        const reader = response.body.getReader();
        const decoder = new TextDecoder(); let buffer = '';
        try {
          while (!this.stopped && generation === this.generation) {
            const part = await reader.read(); if (part.done) break;
            buffer += decoder.decode(part.value, { stream: true }).replace(/\r\n/g, '\n');
            if (buffer.length > 1024 * 1024) throw new Error('Plugin event too large');
            let boundary;
            while ((boundary = buffer.indexOf('\n\n')) >= 0) {
              const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
              const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
              if (!data) continue;
              try {
                const event: unknown = JSON.parse(data);
                if (event && typeof event === 'object' && !Array.isArray(event) && generation === this.generation)
                  this.receive(event as Record<string, unknown>);
              } catch { /* An invalid frame does not terminate the stream. */ }
            }
          }
        } finally { await reader.cancel().catch(() => {}); }
      } catch { /* The WebSocket still reports FRIDAY's availability; retry events quietly. */ }
      if (!this.stopped && generation === this.generation) this.retry = setTimeout(() => void run(), 2000);
    };
    void run();
  }
  stop() { this.stopped = true; ++this.generation; clearTimeout(this.retry); this.abort?.abort(); }
}
