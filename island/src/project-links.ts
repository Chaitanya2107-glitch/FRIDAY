import type { Connection } from './connection';
import type { CommandResult } from './types';
import { element as el } from './state';

export function sharedProjects(host: HTMLElement, connection: Connection, submit: (text: string) => Promise<void>,
                               message: (text: string, bad?: boolean) => void,
                               launch: (result: CommandResult) => Promise<void>) {
  const box = el('section', 'friday-panel'); box.append(el('strong', '', 'FRIDAY projects'));
  const rows = el('div', 'friday-features'); box.append(rows); host.append(box);
  function display(frame: Record<string, unknown>) {
    if (!box.isConnected || !Array.isArray(frame.items)) return;
    rows.replaceChildren();
    for (const item of frame.items) {
      if (!item || typeof item.name !== 'string') continue;
      const button = el('button', 'text-button', item.name + (item.conflict ? ' · review folder' : ''));
      button.title = item.value?.path ?? '';
      button.onclick = () => void (typeof item.native_id === 'string'
        ? launch({ ok: true, text: item.name, action: { kind: 'project', id: item.native_id } }) : submit(`resume ${item.name}`));
      rows.append(button);
    }
    if (!rows.childElementCount) rows.append(el('p', 'muted', 'No registered FRIDAY projects.'));
  }
  void connection.request('projects', {}, 5000).then(display).catch(error => message(String(error), true));
  const sync = el('button', 'text-button', 'Sync saved project folders');
  sync.onclick = async () => {
    sync.disabled = true;
    try {
      const frame = await connection.request('projects', { action: 'import' }, 15000); display(frame);
      const conflicts = Array.isArray(frame.conflicts) ? frame.conflicts.map(String) : [];
      message(conflicts.length ? `Existing projects preserved. Review: ${conflicts.join(', ')}` : 'Project folders registered. Launch actions are preserved.', !!conflicts.length);
    } catch (error) { message(String(error), true); }
    finally { sync.disabled = false; }
  };
  box.append(sync);
}
