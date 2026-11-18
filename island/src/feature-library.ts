import { element as el } from './state';
import type { Connection } from './connection';

interface Feature { key: string; title: string; category: string; description: string; how: string; requires: string; guide: string; examples: string[] }
export class FeatureLibrary {
  private generation = 0;
  constructor(private connection: () => Connection, private fill: (text: string) => void,
              private submit: (text: string) => Promise<void>, private message: (text: string, bad?: boolean) => void) {}
  close() { this.generation++; }
  private button(label: string, action: () => void) {
    const button = el('button', 'text-button', label); button.type = 'button'; button.onclick = action; return button;
  }
  async mount(host: HTMLElement, plugins = false) {
    const generation = ++this.generation;
    const root = el('section', 'feature-library'); host.append(root);
    root.append(el('p', 'muted', plugins ? 'Reading installed plugins…' : 'Reading FRIDAY’s feature catalog…'));
    try {
      const response = await this.connection().request('desktop_tools', { action: plugins ? 'plugins' : 'features' }, 10000);
      if (generation !== this.generation || !root.isConnected) return;
      root.replaceChildren();
      if (plugins) {
        root.append(el('h3', '', 'Installed plugins'));
        if (!Array.isArray(response.items) || !response.items.length) root.append(el('p', 'muted', 'No managed plugins are loaded.'));
        for (const item of Array.isArray(response.items) ? response.items : []) {
          if (!item || typeof item.id !== 'string' || !/^[a-z][a-z0-9_-]{0,63}$/.test(item.id)) continue;
          const card = el('article', 'feature-card');
          card.append(el('strong', '', String(item.name)), el('small', 'muted', String(item.status)), el('p', '', String(item.description ?? '')));
          const action = item.enabled ? 'disable' : 'enable';
          card.append(this.button(`${item.enabled ? 'Disable' : 'Enable'} ${item.name}`, () => void this.submit(`${action} plugin ${item.id}`)));
          for (const command of Array.isArray(item.commands) ? item.commands : []) {
            if (typeof command.help === 'string') card.append(el('p', 'muted', command.help));
            this.examples(card, command.examples);
          }
          root.append(card);
        }
        root.append(this.button('Reload plugins', () => void this.submit('reload plugins')));
        return;
      }
      const features = (Array.isArray(response.items) ? response.items : []) as Feature[];
      const query = el('input'); query.placeholder = 'Find a feature, command or topic'; query.setAttribute('aria-label', 'Search FRIDAY features');
      const category = el('select'); category.setAttribute('aria-label', 'Feature category');
      for (const value of ['', ...new Set(features.map(item => item.category))]) {
        const option = el('option', '', value || 'All features'); option.value = value; category.append(option);
      }
      const list = el('div'); root.append(el('p', 'muted', 'Choose an example to fill the command bar. Review it, then press Enter. Availability depends on the requirements shown.'), query, category, list);
      const paint = () => {
        list.replaceChildren();
        const words = query.value.toLowerCase().split(/\s+/).filter(Boolean);
        for (const item of features) {
          if (category.value && item.category !== category.value) continue;
          const searchable = [item.title, item.category, item.description, ...item.examples].join(' ').toLowerCase();
          if (!words.every(word => searchable.includes(word))) continue;
          const card = el('details', 'feature-card'); card.dataset.feature = item.key;
          card.append(el('summary', '', item.title), el('small', 'muted', item.category), el('p', '', item.description),
            el('p', '', item.how), el('p', 'muted', `Needs: ${item.requires}`));
          this.examples(card, item.examples);
          card.append(this.button('Read guide', () => {
            void this.connection().request('desktop_tools', { action: 'guide', value: item.guide }, 10000).then(result => {
              if (generation !== this.generation || !card.isConnected) return;
              card.querySelector('.feature-guide')?.remove(); card.append(el('pre', 'feature-guide', String(result.text ?? 'Guide unavailable.')));
            }).catch(error => this.message(String(error), true));
          }));
          list.append(card);
        }
        if (!list.childElementCount) list.append(el('p', 'muted', 'No matching feature. Try another word.'));
      };
      query.oninput = category.onchange = paint; paint();
    } catch (error) {
      if (generation === this.generation && root.isConnected) root.replaceChildren(el('p', 'muted', String(error)));
    }
  }
  private examples(host: HTMLElement, values: unknown) {
    for (const value of Array.isArray(values) ? values : []) {
      if (typeof value === 'string' && value.length <= 4000) host.append(this.button(value, () => this.fill(value)));
    }
  }
}
