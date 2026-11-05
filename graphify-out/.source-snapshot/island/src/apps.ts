import { call, native, on } from './native';
import { icon } from './icons';
import { element as el } from './state';
import type { AppMatch, Config, IndexStatus, Suggestion } from './types';

export class Apps {
  status: IndexStatus = { count: 0, scanning: false, updated_at: 0, errors: [] };
  private icons = new Map<string, Promise<string>>();
  private query = '';
  constructor(private changed: (config: Config) => void, private message: (text: string, bad?: boolean) => void) {}
  async start(updated: () => void) {
    if (!native) return;
    await on<IndexStatus>('apps-updated', value => { this.status = value; this.icons.clear(); updated(); });
    try { this.status = await call<IndexStatus>('app_index_status'); updated(); } catch {}
  }
  async search(query: string, limit = 6): Promise<AppMatch[]> {
    if (!native) return [];
    return (await call<AppMatch[]>('search_apps', { query })).slice(0, limit);
  }
  async suggestions(text: string): Promise<Suggestion[]> {
    const query = text.trim().replace(/^open(?:\s+|$)/i, '');
    const matches = await this.search(query);
    return matches.map(app => ({ text: `open ${app.name}`, detail: app.source, app }));
  }
  icon(app: AppMatch): HTMLElement {
    const holder = el('span', 'app-icon'); holder.append(icon('app'));
    if (!native) return holder;
    const key = `${app.kind}:${app.id}`;
    let promise = this.icons.get(key);
    if (!promise) {
      promise = call<string>(app.kind === 'app' ? 'app_icon' : 'pin_icon', { id: app.id }); this.icons.set(key, promise);
    }
    void promise.then(source => {
      if (source.startsWith('data:image/png;base64,')) { const img = el('img'); img.src = source; img.alt = ''; holder.replaceChildren(img); }
    }).catch(() => { this.icons.delete(key); });
    return holder;
  }
  pin(app: AppMatch): HTMLButtonElement {
    const button = el('button', `icon-button app-pin${app.pinned ? ' pinned' : ''}`);
    button.type = 'button'; button.title = `${app.pinned ? 'Unpin' : 'Pin'} ${app.name}`;
    button.setAttribute('aria-label', button.title); button.setAttribute('aria-pressed', String(app.pinned)); button.append(icon('pin'));
    button.onpointerdown = event => event.preventDefault();
    button.onclick = async event => {
      event.stopPropagation(); button.disabled = true;
      try {
        const config = await call<Config>('toggle_app_pin', { id: app.id });
        app.pinned = config.pins.some(p => p.app_id === app.id);
        this.changed(config);
        button.classList.toggle('pinned', app.pinned); button.title = `${app.pinned ? 'Unpin' : 'Pin'} ${app.name}`;
        button.setAttribute('aria-label', button.title); button.setAttribute('aria-pressed', String(app.pinned));
      } catch (error) { this.message(String(error), true); }
      finally { button.disabled = false; }
    };
    return button;
  }
  async rescan() {
    try { this.status = await call<IndexStatus>('rescan_apps'); this.icons.clear(); this.message(this.status.scanning ? 'App scan is already running' : `App scan complete · ${this.status.count} apps`); }
    catch (error) { this.message(String(error), true); }
  }
  render(root: HTMLElement) {
    const section = el('section', 'installed-apps');
    const header = el('div', 'panel-heading');
    const summary = el('small', 'muted', this.status.scanning ? 'Scanning installed apps…' : `${this.status.count} installed apps`);
    const rescan = el('button', 'text-button', 'Rescan apps'); rescan.type = 'button';
    rescan.disabled = this.status.scanning;
    rescan.onclick = async () => { rescan.disabled = true; await this.rescan(); summary.textContent = `${this.status.count} installed apps`; rescan.disabled = false; await refresh(); };
    header.append(el('strong', '', 'Installed apps'), summary, rescan);
    const search = el('input'); search.placeholder = 'Find an installed app…'; search.setAttribute('aria-label', 'Find installed apps');
    search.value = this.query;
    const list = el('div', 'installed-list');
    section.append(header, search, list); root.append(section);
    for (const warning of this.status.errors) section.append(el('p', 'error-text', warning));
    let generation = 0;
    const refresh = async () => {
      const current = ++generation;
      try {
        const apps = await this.search(search.value, 100);
        if (current !== generation || !section.isConnected) return;
        list.replaceChildren(...apps.filter(a => a.kind === 'app').map(app => {
          const row = el('div', 'installed-row');
          const label = el('div', 'installed-label'); label.append(el('span', '', app.name), el('small', 'muted', app.source));
          row.append(this.icon(app), label, this.pin(app)); return row;
        }));
        if (!apps.length) list.append(el('p', 'muted', this.status.scanning ? 'Indexing apps…' : 'No app found. Try Rescan apps.'));
        if (apps.length === 100) list.append(el('small', 'muted', 'Showing 100 matches. Type a name to find more.'));
      } catch (error) { list.replaceChildren(el('p', 'muted', String(error))); }
    };
    let timer: ReturnType<typeof setTimeout>;
    search.oninput = () => { this.query = search.value; clearTimeout(timer); timer = setTimeout(() => void refresh(), 160); };
    void refresh();
  }
}
