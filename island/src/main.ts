import './style.css';
import { Connection } from './connection';
import { Apps } from './apps';
import { call, native, on, previewConfig } from './native';
import { character, icon } from './icons';
import { button, Settings } from './settings';
import { element as el, localSuggestions, transition } from './state';
import type { CommandResult, Config, Manifest, Mode, NativeStatus, Suggestion, Tab } from './types';

const root = document.querySelector<HTMLElement>('#app')!;
const surface = el('section', 'surface'); surface.dataset.hit = ''; surface.dataset.mode = 'rest';
surface.setAttribute('aria-label', 'FRIDAY Island');
const row = el('div', 'island-row');
const orb = character();
const live = el('span', 'live-line', 'FRIDAY offline');
const command = el('input', 'command');
command.placeholder = 'A thought, a command…'; command.autocomplete = 'off'; command.spellcheck = false; command.maxLength = 4000;
command.setAttribute('aria-label', 'FRIDAY command'); command.setAttribute('role', 'combobox');
command.setAttribute('aria-autocomplete', 'list'); command.setAttribute('aria-controls', 'suggestions'); command.setAttribute('aria-expanded', 'false');
const pins = el('div', 'pins');
const projectsButton = button('Projects', 'projects', () => openTab('projects'));
const settingsButton = button('Settings', 'settings', () => openTab('settings'));
const closeButton = button('Close · Esc', 'close', () => dispatch('escape'));
const tools = el('div', 'tools'); tools.append(pins, projectsButton, settingsButton, closeButton);
row.append(orb, live, command, tools);
const results = el('div', 'suggestions'); results.id = 'suggestions'; results.setAttribute('role', 'listbox');
const body = el('div', 'expanded-body');
const tabs = el('nav', 'tabs'); tabs.setAttribute('aria-label', 'Island tabs');
const panels = el('div', 'panels');
const expandedInner = el('div', 'expanded-inner'); expandedInner.append(tabs, panels);
body.append(expandedInner); surface.append(row, results, body);
const feedback = el('div', 'feedback'); feedback.dataset.hit = ''; feedback.setAttribute('role', 'status'); feedback.hidden = true;
root.append(surface, feedback);

let config: Config = previewConfig();
let mode: Mode = 'rest';
let tab: Tab = 'projects';
let connection: Connection;
let online = false;
let snippet = '';
let manifests: Manifest[] = [];
let nativeStatus: NativeStatus = { mode: 'rest', hotkey_errors: [], max_width: 720, max_height: 560, reduce_motion: false };
let suggestions: Suggestion[] = [];
let selected = -1;
let completed: Suggestion | undefined;
let busy = false;
let active = false;
let lastActivity = Date.now();
let leaveTimer: ReturnType<typeof setTimeout>;
let suggestionTimer: ReturnType<typeof setTimeout>;
let feedbackTimer: ReturnType<typeof setTimeout>;
let moodTimer: ReturnType<typeof setTimeout>;
let suggestionGeneration = 0;
const icons = new Map<string, string>();
const apps = new Apps(next => { config = next; applyConfig(); settings.refreshFavourites(); }, message);
const settings = new Settings(panels, {
  config: () => config, status: () => nativeStatus, online: () => online, message,
  apps,
  reload: async () => { config = await call<Config>('get_config'); applyConfig(); connect(); },
  save: async next => {
    const previous = config.connection;
    config = await call<Config>('save_config', { next });
    applyConfig();
    if (previous.port !== config.connection.port || previous.token !== config.connection.token) connect();
  },
});

function message(text: string, bad = false) {
  clearTimeout(feedbackTimer);
  feedback.textContent = text; feedback.classList.toggle('bad', bad);
  if (bad && text.includes('No app found')) {
    const rescan = el('button', 'text-button', 'Rescan apps');
    rescan.onclick = () => void apps.rescan(); feedback.append(rescan);
  }
  feedback.hidden = mode === 'hidden' || mode === 'sneak';
  feedbackTimer = setTimeout(() => { feedback.hidden = true; syncRegions(); }, bad ? 7000 : 3500);
  if (bad) mood('error', 900);
  syncRegions();
}
function mood(value?: string, duration = 0) {
  clearTimeout(moodTimer);
  surface.dataset.mood = value ?? (!online ? 'offline' : mode === 'hidden' || mode === 'sneak' || Date.now() - lastActivity > 60000 ? 'sleepy' : command.value ? 'listening' : 'idle');
  if (duration) moodTimer = setTimeout(() => mood(), duration);
}
let lastLayout = '';
function syncRegions() {
  if (!native) return;
  const nodes = [surface, ...(feedback.hidden ? [] : [feedback])];
  const width = mode === 'hidden' ? 1 : Math.ceil(Math.max(...nodes.map(n => n.getBoundingClientRect().width)) + 20);
  const height = mode === 'hidden' ? 1 : Math.ceil(Math.max(...nodes.map(n => n.getBoundingClientRect().bottom)) + 10);
  const rects = mode === 'hidden' ? [] : nodes.map(node => {
    const r = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return { x: (width - r.width) / 2, y: r.y, width: r.width, height: r.height, radius: parseFloat(style.borderBottomLeftRadius) || 0,
      top_square: parseFloat(style.borderTopLeftRadius) === 0 };
  });
  const layout = JSON.stringify({ width, height, rects });
  if (layout === lastLayout) return;
  lastLayout = layout;
  void call('set_regions', { width, height, rects }).catch(() => { lastLayout = ''; });
}
let animationUntil = 0;
let animating = false;
function animateRegions() {
  animationUntil = performance.now() + 260;
  if (animating) return;
  animating = true;
  const tick = () => { syncRegions(); if (performance.now() < animationUntil) requestAnimationFrame(tick); else animating = false; };
  requestAnimationFrame(tick);
}
new ResizeObserver(syncRegions).observe(surface);
window.addEventListener('resize', syncRegions);

async function setMode(next: Mode, activate = false) {
  clearTimeout(leaveTimer);
  lastActivity = Date.now();
  mode = next; active = activate && ['peek', 'expanded', 'sneak'].includes(next);
  surface.dataset.mode = next;
  root.dataset.mode = next;
  command.placeholder = next === 'sneak' ? 'What would you like to do?' : 'A thought, a command…';
  if (next === 'rest' || next === 'hidden') { command.value = ''; clearSuggestions(); feedback.hidden = true; }
  if (next === 'sneak') feedback.hidden = true;
  body.inert = next !== 'expanded';
  if (next === 'expanded') { clearSuggestions(); renderPanel(); }
  mood(); animateRegions();
  try { if (native) await call('set_mode', { mode: next, activate: active }); if (active) command.focus(); }
  catch (error) { message(String(error), true); }
}
function dispatch(event: Parameters<typeof transition>[1], activate = false) {
  return setMode(transition(mode, event, config.appearance.idle_mode !== 'always'), activate);
}
async function openTab(next: Tab) { tab = next; await setMode('expanded', active); }
surface.onpointerenter = () => { clearTimeout(leaveTimer); if (mode === 'rest') void dispatch('hover'); };
surface.onpointerleave = () => {
  if (mode === 'peek' && !active && !command.value) leaveTimer = setTimeout(() => void dispatch('leave'), 400);
};
surface.addEventListener('pointerdown', event => {
  const target = event.target as HTMLElement;
  if (!target.closest('input,textarea,select') || active) return;
  event.preventDefault();
  active = true;
  void call('set_mode', { mode, activate: true }).then(() => target.focus()).catch(error => message(String(error), true));
});
window.addEventListener('blur', () => { if (mode === 'peek' || mode === 'sneak') void dispatch('escape'); });
window.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); void dispatch('escape'); } });

function applyConfig() {
  document.documentElement.style.setProperty('--accent', config.appearance.glow);
  document.documentElement.style.setProperty('--orb-edge', `color-mix(in srgb, ${config.appearance.glow}, #b65018 45%)`);
  root.classList.toggle('character-only', !config.appearance.snippet);
  renderPins(); updateLive();
  if (config.appearance.idle_mode === 'hover' && mode === 'rest') void setMode('hidden');
}
function updateLive() {
  live.textContent = online ? snippet || 'Here when you need me' : 'FRIDAY offline';
  live.title = live.textContent; surface.classList.toggle('offline', !online); mood();
}
function pinButton(pin: Config['pins'][number]) {
  const node = button(pin.name, 'app', () => perform({ text: pin.name, ok: true, action: { kind: 'pin', id: pin.id } }));
  const cached = icons.get(pin.id);
  if (cached) { const img = el('img'); img.src = cached; img.alt = ''; node.replaceChildren(img); }
  else if (native) void call<string>('pin_icon', { id: pin.id }).then(source => {
    if (!source.startsWith('data:image/png;base64,')) return;
    icons.set(pin.id, source); const img = el('img'); img.src = source; img.alt = ''; node.replaceChildren(img);
  }).catch(() => {});
  return node;
}
function pinLimit() { return (nativeStatus.max_width || 720) < 660 ? 4 : 8; }
function renderPins() { pins.replaceChildren(...config.pins.filter(p => p.visible).slice(0, pinLimit()).map(pinButton)); }
function renderPanel() {
  tabs.replaceChildren();
  for (const id of ['projects', 'plugins', 'settings'] as const) {
    const node = el('button', tab === id ? 'selected' : '', id[0].toUpperCase() + id.slice(1));
    node.onclick = () => { tab = id; renderPanel(); }; tabs.append(node);
  }
  panels.replaceChildren();
  if (tab === 'settings') { settings.render(); return; }
  if (tab === 'plugins') {
    if (!online) panels.append(el('p', 'empty', 'Connect FRIDAY to see your plugins.'));
    for (const manifest of manifests) {
      const widget = el('article', 'widget'); widget.append(el('strong', '', manifest.name), el('p', 'muted', 'Loading…'));
      panels.append(widget);
      void connection.widget(manifest.id).then(data => {
        widget.replaceChildren(el('strong', '', String(data.title)), el('p', '', String(data.text)), el('small', 'muted', manifest.commands.join(' · ')));
        syncRegions();
      }).catch(() => { widget.replaceChildren(el('strong', '', manifest.name), el('p', 'muted', 'Widget unavailable')); });
    }
    return;
  }
  const extras = config.pins.filter(p => p.visible).slice(pinLimit());
  if (extras.length) { const tray = el('div', 'extra-pins'); tray.append(...extras.map(pinButton)); panels.append(tray); }
  const heading = el('div', 'panel-heading'); heading.append(el('span', 'muted', 'A place for every idea'), button('Add project', 'plus', () => { tab = 'settings'; renderPanel(); return settings.addProject(); }));
  panels.append(heading);
  if (!config.projects.length) {
    const empty = el('div', 'empty-projects'); empty.append(icon('folder'), el('p', '', 'Make room for your next idea.'), el('small', 'muted', 'Add a folder. Open everything you need in one click.'));
    panels.append(empty);
  }
  const grid = el('div', 'project-grid');
  for (const project of config.projects) {
    const tile = el('article', 'project-tile'); tile.style.setProperty('--project-accent', project.color);
    const open = el('button', 'project-open'); open.title = `Open ${project.name}`;
    const date = project.last_opened && new Date(Number(project.last_opened) * 1000);
    open.append(icon('folder'), el('strong', '', project.name), el('small', 'muted', date && !Number.isNaN(+date) ? `Opened ${date.toLocaleDateString()}` : 'Ready when you are'));
    open.onclick = () => void perform({ text: project.name, ok: true, action: { kind: 'project', id: project.id } });
    tile.append(open, button(`Edit ${project.name}`, 'edit', () => { tab = 'settings'; renderPanel(); settings.editProject(project); }));
    grid.append(tile);
  }
  panels.append(grid);
}

function renderSuggestions() {
  results.replaceChildren();
  command.setAttribute('aria-expanded', String(suggestions.length > 0));
  if (selected >= 0) command.setAttribute('aria-activedescendant', `suggestion-${selected}`); else command.removeAttribute('aria-activedescendant');
  suggestions.forEach((item, index) => {
    const node = el('div', index === selected ? 'suggestion selected' : 'suggestion');
    node.id = `suggestion-${index}`; node.setAttribute('role', 'option'); node.setAttribute('aria-selected', String(index === selected));
    const execute = el('button', 'suggestion-run'); execute.type = 'button'; execute.tabIndex = -1;
    if (item.app) execute.append(apps.icon(item.app));
    execute.append(el('span', 'suggestion-label', item.text), el('small', 'muted', item.detail ?? 'Command'));
    execute.onpointerdown = event => event.preventDefault(); execute.onclick = () => void run(item.text, item);
    node.append(execute);
    if (item.app?.kind === 'app') node.append(apps.pin(item.app));
    results.append(node);
  });
  results.hidden = !suggestions.length;
  surface.style.setProperty('--results-height', `${results.hidden ? 0 : results.offsetHeight}px`);
  syncRegions();
}
function clearSuggestions(keepCompletion = false) {
  clearTimeout(suggestionTimer); ++suggestionGeneration;
  if (!keepCompletion) completed = undefined;
  selected = -1; suggestions = []; renderSuggestions();
}
command.oninput = () => {
  completed = undefined;
  lastActivity = Date.now(); mood();
  clearTimeout(suggestionTimer);
  const generation = ++suggestionGeneration;
  const text = command.value;
  selected = -1;
  suggestionTimer = setTimeout(() => {
    const explicit = /^open(?:\s|$)/i.test(text.trim());
    let local: Suggestion[] = [], brain: Suggestion[] = [], localDone = false;
    const publish = () => {
      if (generation !== suggestionGeneration) return;
      const previous = suggestions[selected];
      suggestions = [...brain, ...local].slice(0, 6);
      if (explicit && localDone && !suggestions.length) suggestions.push({ text: 'No app found · Rescan apps', detail: 'Rescan', rescan: true });
      if (previous) selected = suggestions.findIndex(s => previous.app ? s.app?.id === previous.app.id : s.text === previous.text);
      renderSuggestions();
    };
    void (isBrainCommand(text) ? Promise.resolve([]) : apps.suggestions(text)).then(items => { local = items; localDone = true; publish(); }, () => { localDone = true; publish(); });
    void (explicit ? Promise.resolve([]) : online ? connection.suggestions(text) : Promise.resolve(localSuggestions(text, config).filter(t => !t.startsWith('open ')).map(text => ({ text })))).then(items => { brain = items; publish(); }, () => { brain = []; publish(); });
  }, 160);
};
function isBrainCommand(text: string) {
  const head = text.trim().split(/\s+/)[0].toLowerCase();
  return ['proj', 'settings', 'next', 'habit', 'todo', 'note', 'focus', ...manifests.flatMap(m => m.commands)].includes(head);
}
command.onkeydown = event => {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault(); selected = suggestions.length ? (selected + (event.key === 'ArrowDown' ? 1 : -1) + suggestions.length) % suggestions.length : -1; renderSuggestions();
  } else if (event.key === 'Tab' && suggestions.length) {
    event.preventDefault();
    const item = suggestions[Math.max(selected, 0)];
    if (item.rescan) { void run(item.text, item); return; }
    completed = item; command.value = item.text; clearSuggestions(true);
  } else if (event.key === 'Enter') { event.preventDefault(); const item = suggestions[selected] ?? (completed?.text === command.value ? completed : undefined); void run(item?.text ?? command.value, item); }
};
async function perform(result: CommandResult) {
  if (!result.ok) { message(result.text, true); return; }
  const action = result.action;
  if (action?.kind === 'app_search') { await perform(await call<CommandResult>('local_command', { text: `open ${action.query ?? ''}` })); return; }
  if (action?.kind === 'settings') { tab = 'settings'; await setMode('expanded', active); return; }
  try {
    let text = result.text;
    if (action) {
      if (!['pin', 'project', 'app'].includes(action.kind) || typeof action.id !== 'string') throw Error('Unsupported backend action');
      text = await call<string>('launch', { kind: action.kind, id: action.id });
      config = await call<Config>('get_config');
    }
    message(text); mood('happy', 1000);
  } catch (error) { message(String(error), true); }
}
async function run(text: string, item?: Suggestion) {
  if (item?.rescan) { await apps.rescan(); command.oninput?.(new Event('input')); return; }
  if (busy || !text.trim()) return;
  busy = true; command.disabled = true;
  const sneak = mode === 'sneak';
  if (sneak) await dispatch('escape');
  try {
    let result: CommandResult;
    const local = native && /^(?:open|proj|settings)(?:\s|$)/i.test(text.trim());
    const exact = !item?.app && !local && native && !isBrainCommand(text) ? (await apps.search(text, 1).catch(() => [])).find(a => a.name.toLowerCase() === text.trim().toLowerCase()) : undefined;
    const target = item?.app ?? exact;
    if (target) result = { ok: true, text: `Opening ${target.name}`, action: { kind: target.kind, id: target.id } };
    else result = local ? await call<CommandResult>('local_command', { text }) : online ? await connection.command(text) : native ? await call<CommandResult>('local_command', { text })
      : { text: 'Desktop commands are available in the Tauri app.', ok: false };
    await perform(result);
    command.value = ''; clearSuggestions();
  } catch (error) { message(String(error), true); }
  finally { busy = false; command.disabled = false; if (active) command.focus(); }
}
function connect() {
  connection?.stop();
  online = false; manifests = []; updateLive();
  connection = new Connection(config.connection, frame => {
    if (frame.type === 'pill_snippet_update' && typeof frame.text === 'string') { snippet = frame.text.slice(0, 80); updateLive(); }
    if (frame.type === 'plugin_list' && Array.isArray(frame.plugins)) {
      manifests = frame.plugins.filter((m): m is Manifest => typeof m === 'object' && m !== null && typeof m.id === 'string' && typeof m.name === 'string' && Array.isArray(m.commands));
      if (mode === 'expanded' && tab === 'plugins') renderPanel();
    }
  }, connected => { online = connected; updateLive(); if (!connected) manifests = []; });
  if (native) connection.start();
}
async function boot() {
  try { if (native) { config = await call<Config>('get_config'); nativeStatus = await call<NativeStatus>('runtime_status'); } }
  catch (error) { message(String(error), true); }
  applyConfig(); connect();
  await apps.start(() => { icons.clear(); renderPins(); if (mode === 'expanded' && tab === 'settings' && settings.section === 'apps') settings.render(); });
  applyLimits();
  document.documentElement.classList.toggle('reduce-motion', nativeStatus.reduce_motion);
  await on<string>('hotkey', event => { if (event === 'sneak' || event === 'expand' || event === 'escape') void dispatch(event, event !== 'escape'); });
  await on<NativeStatus>('native-status', status => {
    nativeStatus = status; applyLimits(); document.documentElement.classList.toggle('reduce-motion', status.reduce_motion);
    if (mode === 'expanded' && tab === 'settings' && settings.section === 'hotkeys') settings.render();
  });
  await on<{ x: number; y: number; reveal: boolean }>('pointer', point => {
    if (point.reveal && mode === 'hidden') void dispatch('hover');
    if (mode === 'hidden' || mode === 'sneak') return;
    const bounds = orb.getBoundingClientRect();
    orb.style.setProperty('--eye-x', `${Math.max(-3, Math.min(3, (point.x - bounds.x - bounds.width / 2) / 90))}px`);
    orb.style.setProperty('--eye-y', `${Math.max(-2, Math.min(2, (point.y - bounds.y - bounds.height / 2) / 90))}px`);
  });
  setInterval(() => {
    if (config.appearance.idle_mode !== 'always' && !active && !command.value && mode === 'rest' && Date.now() - lastActivity > config.appearance.idle_seconds * 1000) void dispatch('idle');
    mood();
  }, 5000);
  syncRegions();
}
void boot();

function applyLimits() {
  const previous = document.documentElement.style.getPropertyValue('--layout-width');
  document.documentElement.style.setProperty('--layout-width', `${nativeStatus.max_width || 720}px`);
  document.documentElement.style.setProperty('--layout-height', `${nativeStatus.max_height || 560}px`);
  renderPins();
  if (previous && previous !== `${nativeStatus.max_width || 720}px` && mode === 'expanded' && tab === 'projects') renderPanel();
  syncRegions();
}
