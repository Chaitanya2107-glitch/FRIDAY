import { call, native } from './native';
import { element as el } from './state';
import { icon } from './icons';
import type { Config, NativeStatus, OpenAction, Pin, Project } from './types';

type Section = 'appearance' | 'apps' | 'projects' | 'hotkeys' | 'connection';
interface Host {
  config: () => Config;
  save: (next: Config) => Promise<void>;
  status: () => NativeStatus;
  online: () => boolean;
  reload: () => Promise<void>;
  message: (text: string, bad?: boolean) => void;
}
export function button(label: string, glyph: string, action: () => unknown, className = 'icon-button'): HTMLButtonElement {
  const node = el('button', className);
  node.type = 'button';
  node.title = label;
  node.setAttribute('aria-label', label);
  node.append(icon(glyph));
  node.onclick = () => { try { Promise.resolve(action()).catch(error => console.error(String(error))); } catch (error) { console.error(String(error)); } };
  return node;
}
function textButton(text: string, action: () => unknown, glyph = 'plus') {
  const node = button(text, glyph, action, 'text-button');
  node.append(el('span', '', text));
  return node;
}
function field(label: string, control: HTMLElement, hint?: string) {
  const row = el('label', 'field');
  row.append(el('span', 'field-label', label), control);
  if (hint) row.append(el('small', 'muted', hint));
  return row;
}
function input(value: string, type = 'text') {
  const node = el('input'); node.type = type; node.value = value; return node;
}
function select(value: string, options: [string, string][]) {
  const node = el('select');
  for (const [key, text] of options) { const option = el('option', '', text); option.value = key; node.append(option); }
  node.value = value; return node;
}

export class Settings {
  section: Section = 'appearance';
  private editor?: Project;
  private confirmRemove?: string;
  constructor(private root: HTMLElement, private host: Host) {}

  async persist(next: Config) {
    try { await this.host.save(next); this.host.message('Saved'); this.render(); }
    catch (error) { this.host.message(String(error), true); }
  }
  change(edit: (config: Config) => void) {
    const next = structuredClone(this.host.config()); edit(next); return this.persist(next);
  }
  render() {
    this.root.replaceChildren();
    if (this.editor) { this.renderProjectEditor(this.editor); return; }
    const nav = el('div', 'settings-nav');
    for (const [key, label] of [['appearance', 'Look'], ['apps', 'Apps'], ['projects', 'Projects'], ['hotkeys', 'Hotkeys'], ['connection', 'Connection']] as const) {
      const node = el('button', this.section === key ? 'selected' : '', label);
      node.onclick = () => { this.section = key; this.render(); };
      nav.append(node);
    }
    this.root.append(nav);
    const config = this.host.config();
    if (this.section === 'appearance') {
      const glow = input(config.appearance.glow, 'color');
      glow.onchange = () => void this.change(c => { c.appearance.glow = glow.value; });
      const idle = select(config.appearance.idle_mode, [['always', 'Always visible'], ['auto-hide', 'Auto-hide when idle'], ['hover', 'Hidden until top-edge hover']]);
      idle.onchange = () => void this.change(c => { c.appearance.idle_mode = idle.value as Config['appearance']['idle_mode']; });
      const seconds = input(String(config.appearance.idle_seconds), 'number'); seconds.min = '5'; seconds.max = '3600';
      seconds.onchange = () => void this.change(c => { c.appearance.idle_seconds = Number(seconds.value); });
      const snippet = input('', 'checkbox'); snippet.checked = config.appearance.snippet;
      snippet.onchange = () => void this.change(c => { c.appearance.snippet = snippet.checked; });
      const sample = el('div', 'theme-sample'); sample.append(el('span', 'sample-dot'), el('div', '', 'A little light. A little space.'));
      this.root.append(sample, field('Character glow', glow), field('When idle', idle), field('Idle delay (seconds)', seconds), field('Show one live line', snippet));
      this.root.append(el('p', 'muted', this.host.status().reduce_motion ? 'Windows reduced motion is on.' : 'Animations follow Windows motion preferences.'));
    } else if (this.section === 'apps') {
      this.root.append(el('p', 'muted', 'Your first eight visible apps appear in Peek. Drag to reorder.'));
      this.renderList('pins');
      this.root.append(textButton('Add app', () => this.addPin()));
    } else if (this.section === 'projects') {
      this.renderList('projects');
      this.root.append(textButton('Add project', () => this.addProject()));
    } else if (this.section === 'hotkeys') {
      for (const [key, title] of [['sneak', 'Sneak mode'], ['expand', 'Peek / expand']] as const) {
        const node = input(config.hotkeys[key]);
        node.onchange = () => void this.change(c => { c.hotkeys[key] = node.value; });
        this.root.append(field(title, node));
      }
      this.root.append(el('p', 'muted', 'Ctrl, Shift, Alt or Win + a letter, number, Space or F1–F24. Esc closes the island.'));
      for (const error of this.host.status().hotkey_errors) this.root.append(el('p', 'error-text', error));
    } else {
      const port = input(String(config.connection.port), 'number'); port.min = '1024'; port.max = '65535';
      port.onchange = () => void this.change(c => { c.connection.port = Number(port.value); });
      this.root.append(el('div', 'connection-label', this.host.online() ? '● FRIDAY connected' : '○ FRIDAY offline'), field('Backend port', port, '127.0.0.1 only. Restart the Python bridge after changing this.'));
      this.root.append(el('p', 'muted', native ? 'Apps, projects and settings work without the backend. Config lives in %APPDATA%\\FRIDAY\\island\\config.json.' : 'Browser preview. Launch with npm run tauri dev for desktop controls.'));
      this.root.append(el('p', 'muted', 'Transparent window · glass is drawn only on the island.'));
      this.root.append(textButton('Reload config', async () => { await this.host.reload(); this.host.message('Config reloaded'); this.render(); }, 'back'));
      this.root.append(textButton('Quit Island', () => call('quit'), 'power'));
    }
  }

  private renderList(kind: 'pins' | 'projects') {
    const config = this.host.config();
    const items = kind === 'pins' ? config.pins : config.projects;
    if (!items.length) this.root.append(el('p', 'empty', kind === 'pins' ? 'Keep your everyday apps close.' : 'Give your next idea a place.'));
    items.forEach((item, index) => {
      const row = el('div', 'config-row'); row.draggable = true;
      row.ondragstart = event => event.dataTransfer?.setData('text/plain', String(index));
      row.ondragover = event => event.preventDefault();
      row.ondrop = event => {
        event.preventDefault();
        const from = Number(event.dataTransfer?.getData('text/plain'));
        if (Number.isInteger(from) && from >= 0 && from < items.length && from !== index) void this.reorder(kind, from, index);
      };
      const grip = el('span', 'grip'); grip.append(icon('grip'));
      const name = input(item.name); name.maxLength = 80; name.setAttribute('aria-label', `${item.name} display name`);
      name.onchange = () => void this.change(c => { (kind === 'pins' ? c.pins : c.projects)[index].name = name.value; });
      row.append(grip, name);
      if (kind === 'pins') {
        const visible = input('', 'checkbox'); visible.checked = (item as Pin).visible; visible.title = 'Show in Island'; visible.setAttribute('aria-label', `Show ${item.name}`);
        visible.onchange = () => void this.change(c => { c.pins[index].visible = visible.checked; });
        row.append(visible);
      } else row.append(button(`Edit ${item.name}`, 'edit', () => this.editProject(item as Project)));
      row.append(button(`Move ${item.name} up`, 'up', () => index > 0 && this.reorder(kind, index, index - 1)),
        button(`Move ${item.name} down`, 'down', () => index < items.length - 1 && this.reorder(kind, index, index + 1)),
        button(`Remove ${item.name}`, this.confirmRemove === item.id ? 'close' : 'trash', () => {
          if (this.confirmRemove !== item.id) { this.confirmRemove = item.id; this.host.message('Click remove again to confirm'); this.render(); return; }
          this.confirmRemove = undefined;
          return this.change(c => { if (kind === 'pins') c.pins.splice(index, 1); else c.projects.splice(index, 1); });
        }));
      this.root.append(row);
    });
  }
  private reorder(kind: 'pins' | 'projects', from: number, to: number) {
    return this.change(c => {
      const rows = kind === 'pins' ? c.pins : c.projects;
      const [row] = rows.splice(from, 1); (rows as (Pin | Project)[]).splice(to, 0, row);
    });
  }
  async addPin() {
    try {
      const picked = await call<{ name: string; path: string } | null>('choose_path', { folder: false });
      if (picked) await this.change(c => c.pins.push({ ...picked, id: crypto.randomUUID(), visible: true }));
    } catch (error) { this.host.message(String(error), true); }
  }
  async addProject() {
    try {
      const picked = await call<{ name: string; path: string } | null>('choose_path', { folder: true });
      if (picked) { this.editor = { ...picked, id: crypto.randomUUID(), color: this.host.config().appearance.glow, last_opened: null, actions: [{ kind: 'folder' }] }; this.render(); }
    } catch (error) { this.host.message(String(error), true); }
  }
  editProject(project: Project) { this.section = 'projects'; this.editor = structuredClone(project); this.render(); }
  private renderProjectEditor(project: Project) {
    const heading = el('div', 'editor-heading');
    heading.append(button('Back to settings', 'back', () => { this.editor = undefined; this.render(); }), el('strong', '', 'Project details'));
    this.root.append(heading);
    const form = el('form', 'project-form');
    const name = input(project.name); name.required = true; name.maxLength = 80;
    const path = input(project.path); path.required = true;
    const color = input(project.color, 'color');
    form.append(field('Name', name), field('Folder', path), field('Accent', color), el('p', 'muted', 'Actions run in this order. Arguments are a JSON array; {path} inserts the folder. No shell is inserted automatically.'));
    const actions = el('div', 'action-list');
    const redraw = () => {
      actions.replaceChildren();
      project.actions.forEach((action, index) => {
        const group = el('div', 'action-editor');
        const kind = select(action.kind, [['folder', 'Open in Explorer'], ['editor', 'Open in editor'], ['terminal', 'New terminal / command'], ['url', 'Open URL']]);
        kind.setAttribute('aria-label', `Action ${index + 1} type`);
        kind.onchange = () => {
          project.actions[index] = kind.value === 'folder' ? { kind: 'folder' } : kind.value === 'url' ? { kind: 'url', url: '' }
            : { kind: kind.value as 'editor' | 'terminal', executable: '', args: kind.value === 'editor' ? ['{path}'] : [] };
          redraw();
        };
        const top = el('div', 'action-heading'); top.append(kind, button(`Remove action ${index + 1}`, 'trash', () => { project.actions.splice(index, 1); redraw(); })); group.append(top);
        if (action.kind === 'url') {
          const url = input(action.url, 'url'); url.placeholder = 'https://…'; url.required = true;
          url.oninput = () => { action.url = url.value; }; group.append(field('URL', url));
        } else if (action.kind !== 'folder') {
          const executable = input(action.executable); executable.placeholder = 'C:\\…\\editor.exe'; executable.required = true;
          executable.oninput = () => { action.executable = executable.value; };
          const args = input(JSON.stringify(action.args)); args.setAttribute('aria-label', 'Arguments as JSON array');
          args.oninput = () => {
            try { const parsed: unknown = JSON.parse(args.value); if (!Array.isArray(parsed) || !parsed.every(a => typeof a === 'string')) throw Error(); action.args = parsed; args.setCustomValidity(''); }
            catch { args.setCustomValidity('Enter a JSON array of strings'); }
          };
          const pick = textButton('Choose executable', async () => {
            try { const value = await call<{ path: string } | null>('choose_path', { folder: false }); if (value) { action.executable = value.path; executable.value = value.path; } }
            catch (error) { this.host.message(String(error), true); }
          }, 'folder');
          group.append(field('Executable (.exe)', executable), pick, field('Arguments', args));
        }
        actions.append(group);
      });
    };
    redraw(); form.append(actions, textButton('Add action', () => { if (project.actions.length < 8) { project.actions.push({ kind: 'folder' }); redraw(); } }));
    const save = el('button', 'primary-button', 'Save project'); save.type = 'submit'; form.append(save);
    form.onsubmit = async event => {
      event.preventDefault();
      const next = structuredClone(this.host.config());
      project.name = name.value.trim(); project.path = path.value.trim(); project.color = color.value;
      const index = next.projects.findIndex(p => p.id === project.id);
      if (index === -1) next.projects.push(project); else next.projects[index] = project;
      try { await this.host.save(next); this.editor = undefined; this.host.message('Project saved'); this.render(); }
      catch (error) { this.host.message(String(error), true); }
    };
    this.root.append(form);
  }
}
