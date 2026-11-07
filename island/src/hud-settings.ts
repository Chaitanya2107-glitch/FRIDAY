import { call, native } from './native';
import type { HudSettings, HudState } from './hud-model';

export async function hudSettings(root: HTMLElement, request: (path: string, method?: string, body?: Record<string, unknown>) => Promise<Record<string, unknown>>) {
  const note = document.createElement('p'); note.className = 'muted'; note.textContent = 'Loading HUD settings…'; root.append(note);
  try {
    const state = await request('hud/state') as unknown as HudState;
    if (!root.contains(note)) return;
    note.textContent = 'Transparent amber instruments. In desktop mode, normal windows cover the HUD.';
    const settings = state.settings;
    const form = document.createElement('form');
    async function change(patch: Partial<HudSettings>) {
      try {
        const result = await request('hud/actions/settings', 'POST', patch);
        if (!result.ok) throw Error(String(result.text));
        note.textContent = 'HUD settings saved.';
      } catch (error) { note.textContent = String(error); }
    }
    function field(label: string, control: HTMLElement) {
      const row = document.createElement('label'); row.className = 'field';
      const title = document.createElement('span'); title.className = 'field-label'; title.textContent = label;
      row.append(title, control); form.append(row);
    }
    function toggle(key: keyof HudSettings, label: string) {
      const input = document.createElement('input'); input.type = 'checkbox'; input.checked = settings[key] === true;
      input.onchange = () => void change({ [key]: input.checked }); field(label, input);
    }
    toggle('enabled', 'HUD enabled');
    const layer = document.createElement('select');
    for (const [value, title] of [['desktop', 'Desktop · behind applications'], ['top', 'On top · reduced opacity']]) {
      const option = document.createElement('option'); option.value = value; option.textContent = title; layer.append(option);
    }
    layer.value = settings.layer; layer.onchange = () => void change({ layer: layer.value as HudSettings['layer'] }); field('Layer', layer);
    const monitors = native ? await call<string[]>('hud_monitors') : [];
    const monitor = document.createElement('select');
    for (const name of ['primary', ...new Set([...monitors, settings.monitor])].filter((name, index, all) => all.indexOf(name) === index)) {
      const option = document.createElement('option'); option.value = name; option.textContent = name === 'primary' ? 'Primary monitor' : name; monitor.append(option);
    }
    monitor.value = settings.monitor; monitor.onchange = () => void change({ monitor: monitor.value }); field('Monitor', monitor);
    for (const [key, label, min, max, step] of [['x', 'Left (logical pixels)', 0, 16000, 1], ['y', 'Top (logical pixels)', 0, 16000, 1],
      ['width', 'Width', 300, 16000, 1], ['height', 'Height', 360, 16000, 1], ['opacity', 'On-top opacity', .2, 1, .05],
      ['battery_threshold', 'Automatic saver below battery %', 1, 100, 1]] as const) {
      const input = document.createElement('input'); input.type = 'number'; input.min = String(min); input.max = String(max); input.step = String(step);
      input.value = String(settings[key]); input.onchange = () => void change({ [key]: Number(input.value) }); field(label, input);
    }
    toggle('hide_fullscreen', 'Hide for fullscreen applications'); toggle('hide_game', 'Hide during the game scene');
    toggle('saver', 'Battery saver (five-second readings)'); toggle('auto_saver', 'Automatic saver when unplugged');
    for (const [key, title] of [['system', 'System rings'], ['network', 'Network'], ['clock', 'Clock & date'], ['class', 'Next class'],
      ['focus', 'Focus timer'], ['scene', 'Scene tag'], ['activity', 'Activity categories']] as const) {
      const input = document.createElement('input'); input.type = 'checkbox'; input.checked = settings.widgets[key];
      input.onchange = () => void change({ widgets: { ...settings.widgets, [key]: input.checked } });
      input.addEventListener('change', () => { settings.widgets[key] = input.checked; }); field(title, input);
    }
    for (const [title, action] of [['Edit layout', () => change({ enabled: true, editing: true })],
      ['Done · save layout', async () => { await change(await call<Partial<HudSettings>>('hud_geometry')); }]] as const) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'text-button'; button.textContent = title;
      button.onclick = () => void action(); form.append(button);
    }
    root.append(form);
  } catch { note.textContent = 'HUD plugin is unavailable. Enable the hud plugin and connect FRIDAY to configure it.'; }
}
