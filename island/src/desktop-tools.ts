import { element as el } from './state';
import type { Connection } from './connection';

export class DesktopTools {
  private root = el('section', 'desktop-tools');
  private generation = 0;
  constructor(private connection: () => Connection, private submit: (text: string) => Promise<void>,
              private message: (text: string, bad?: boolean) => void) {}

  close() {
    this.generation++;
    this.root.replaceChildren();
    void this.connection().request('desktop_tools', { action: 'close' }, 3000).catch(() => {});
  }
  mount(host: HTMLElement) { host.append(this.root); void this.refresh(); }
  private button(label: string, action: () => Promise<unknown>) {
    const node = el('button', 'text-button', label); node.type = 'button';
    node.onclick = () => { node.disabled = true; void action().catch(error => this.message(String(error), true)).finally(() => { node.disabled = false; }); };
    return node;
  }
  private async request(action: string, item = '', value = '') {
    const result = await this.connection().request('desktop_tools', { action, item, value }, 10000);
    if (typeof result.text === 'string') this.message(result.text, result.ok === false);
    return result;
  }
  private async refresh() {
    const generation = ++this.generation;
    this.root.replaceChildren(el('p', 'muted', 'Loading desktop tools…'));
    try {
      const data = await this.request('read');
      if (generation !== this.generation || !this.root.isConnected) return;
      this.root.replaceChildren(this.button('Refresh tools', () => this.refresh()));
      for (const warning of Array.isArray(data.warnings) ? data.warnings : []) {
        if (typeof warning === 'string') this.root.append(el('p', 'muted', warning));
      }
      this.root.append(el('h3', '', 'Clipboard history · private'));
      const clips = Array.isArray(data.clipboard) ? data.clipboard : [];
      if (!clips.length) this.root.append(el('p', 'muted', 'Clipboard history is empty.'));
      for (const item of clips) {
        if (!item || typeof item.id !== 'string' || typeof item.text !== 'string') continue;
        const row = el('div', 'clipboard-entry');
        row.append(el('p', '', item.text), this.button('Copy', () => this.request('clipboard_copy', item.id)));
        this.root.append(row);
      }
      this.root.append(this.button('Clear clipboard history', async () => {
        if (window.confirm('Clear saved clipboard history?')) { await this.request('clipboard_clear'); await this.refresh(); }
      }));
      this.root.append(el('h3', '', 'Indexed files'));
      const files = data.files as Record<string, unknown> | undefined;
      const folders = files && Array.isArray(files.folders) ? files.folders.join('\n') : '';
      this.root.append(el('p', 'muted', files ? `${files.enabled ? 'Enabled' : 'Disabled'} · ${files.files ?? files.count ?? 0} indexed files${files.scanning ? ' · Scanning…' : ''}${folders ? `\n${folders}` : ''}` : 'File index unavailable.'));
      const form = el('form'); const query = el('input'); query.maxLength = 160;
      query.placeholder = 'Find an indexed file'; query.setAttribute('aria-label', 'Search indexed files');
      const find = el('button', 'text-button', 'Search'); find.type = 'submit'; const results = el('div');
      form.append(query, find); this.root.append(form, results);
      form.onsubmit = event => {
        event.preventDefault();
        if (!query.value.trim()) return;
        find.disabled = true;
        void this.request('files_search', '', query.value).then(data => {
          if (generation !== this.generation) return;
          results.replaceChildren();
          if (data.ok === false) return;
          for (const hit of Array.isArray(data.results) ? data.results : []) {
            if (typeof hit.name === 'string' && typeof hit.path === 'string') {
              const row = el('div', 'file-result'); row.append(el('p', '', `${hit.name}\n${hit.path}`));
              if (typeof hit.id === 'string') row.append(this.button('Open file', () => this.request('files_open', hit.id)),
                this.button('Show in folder', () => this.request('files_reveal', hit.id)));
              results.append(row);
            }
          }
          if (!results.childElementCount) results.append(el('p', 'muted', 'No indexed files found.'));
        }).catch(error => this.message(String(error), true)).finally(() => { find.disabled = false; });
      };
      this.root.append(this.button('Rescan files', () => this.request('files_rescan')));
      this.root.append(el('h3', '', 'System'), el('p', '', Array.isArray(data.stats) ? data.stats.join('\n') : 'Unavailable'));
      this.root.append(el('h3', '', 'Saved routines'));
      for (const name of Array.isArray(data.routines) ? data.routines : []) {
        if (typeof name === 'string') this.root.append(this.button(name, () => this.submit(`run ${name}`)));
      }
    } catch (error) {
      if (generation === this.generation) this.root.replaceChildren(el('p', 'muted', String(error)), this.button('Retry', () => this.refresh()));
    }
  }
}
