// This finite subset is also checked against the live laptop registry before execution.
export const SAFE_COMMANDS = new Set(['start_focus', 'stop_focus', 'set_scene', 'add_note', 'ring_laptop']);
export const queueable = command => SAFE_COMMANDS.has(command);
export const QUEUE_INTERVAL_MS = 2500;
export function queuedCommand(command, args = {}, ttl = 900, now = Math.floor(Date.now() / 1000)) {
  if (!queueable(command)) throw Error('This command cannot be queued.');
  if (!Number.isInteger(ttl) || ttl < 1 || ttl > 86400) throw Error('Expiry must be between 1 second and 24 hours.');
  return { id: crypto.randomUUID(), command, args: structuredClone(args), created: now, expires_at: now + ttl, state: 'waiting' };
}
export function indexedQueue() {
  async function operation(mode, callback) {
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('friday-remote-queue', 1);
      request.onupgradeneeded = () => {
        const store = request.result.createObjectStore('commands', { keyPath: 'sequence', autoIncrement: true });
        store.createIndex('id', 'id', { unique: true });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      return await new Promise((resolve, reject) => {
        const transaction = db.transaction('commands', mode);
        const request = callback(transaction.objectStore('commands'));
        transaction.oncomplete = () => resolve(request?.result);
        transaction.onabort = transaction.onerror = () => reject(transaction.error || Error('Queue storage unavailable.'));
      });
    } finally { db.close(); }
  }
  return {
    list: () => operation('readonly', store => store.getAll()),
    put: row => operation('readwrite', store => store.put(row)),
    remove: id => operation('readwrite', store => {
      const lookup = store.index('id').getKey(id);
      lookup.onsuccess = () => { if (lookup.result !== undefined) store.delete(lookup.result); };
      return lookup;
    }),
    clear: () => operation('readwrite', store => store.clear()),
  };
}
export class CommandQueue {
  constructor(store, send, { clock = () => Math.floor(Date.now() / 1000), wait = ms => new Promise(resolve => setTimeout(resolve, ms)), changed = () => {} } = {}) {
    Object.assign(this, { store, send, clock, wait, changed });
    this.draining = false;
  }
  async enqueue(command, args = {}, ttl = 900) {
    if ((await this.store.list()).length >= 100) throw Error('Queue full. Cancel an old request before adding another.');
    const row = queuedCommand(command, args, ttl, this.clock());
    await this.store.put(row); await this.changed(); return row;
  }
  async rows() {
    const rows = (await this.store.list()).sort((a, b) => a.created - b.created || (a.sequence || 0) - (b.sequence || 0));
    for (const row of rows) if (row.state === 'waiting' && row.expires_at <= this.clock()) {
      row.state = 'expired'; await this.store.put(row);
    }
    return rows;
  }
  async drain() {
    if (this.draining) return;
    this.draining = true;
    try {
      for (const row of await this.rows()) {
        if (row.state !== 'waiting') continue;
        // A cancellation or expiry while a previous request was running must win.
        if (!(await this.store.list()).some(current => current.id === row.id)) continue;
        if (row.expires_at <= this.clock()) { await this.rows(); continue; }
        if (!queueable(row.command)) { row.state = 'refused'; await this.store.put(row); continue; }
        const { id, created, expires_at, command, args } = row;
        this.activeId = id; await this.changed();
        try {
          const reply = await this.send({ id, created, expires_at, command, args });
          if (reply.result === 'completed') await this.store.remove(id);
          else { row.state = reply.result === 'uncertain' ? 'uncertain' : 'refused'; await this.store.put(row); }
        } catch (error) {
          if (error.networkUnavailable) break;
          row.state = error.requestRefused ? 'refused' : 'uncertain'; await this.store.put(row);
        }
        this.activeId = null; await this.changed();
        await this.wait(QUEUE_INTERVAL_MS);
      }
    } finally { this.activeId = null; this.draining = false; await this.changed(); }
  }
}
