import './style.css';
import './friday.css';
import './capsule-layout.css';
import { FridayPanel } from './friday';
import { sharedProjects } from './project-links';
import { Connection } from './connection';
import { Apps } from './apps';
import { Capsule } from './capsule';
import { HudController } from './hud-controller';
import { BootAnimation } from './boot';
import { MochiDisplay } from './mochi-display';
import { ReplySurface } from './reply-surface';
import { briefingCard } from './plugin-card';
import { SceneState } from './scene-state';
import { matchesDismiss } from './hotkeys';
import { isFileReference, resolveSlash, slashSuggestions } from './slash-commands';
import { PluginWidgets } from './widgets';
import { call, native, on, previewConfig, startupState } from './native';
import { character, icon } from './icons';
import { button, Settings } from './settings';
import { element as el, localSuggestions, readReminder, sneakMode, transition } from './state';
import type { CommandResult, Config, ExecutionTarget, Manifest, Mode, NativeStatus, PillSnippet, Suggestion, Tab } from './types';

const root = document.querySelector<HTMLElement>('#app')!;
let sneakEnabled = false;
try { sneakEnabled = localStorage.getItem('friday.sneak') === 'true'; } catch { /* Session toggle still works without storage. */ }
const surface = el('section', 'surface'); surface.dataset.hit = ''; surface.dataset.mode = sneakEnabled ? 'hidden' : 'rest';
root.dataset.mode = surface.dataset.mode;
surface.setAttribute('aria-label', 'FRIDAY Island');
const row = el('div', 'island-row');
const orb = character();
orb.onpointerdown = event => { if (event.button === 0) event.preventDefault(); };
const capsule = new Capsule(message);
const live = el('span', 'live-line', 'FRIDAY offline');
const sceneState = new SceneState();
let sceneCardVersion = 0;
const sceneChip = el('button', 'scene-chip'); sceneChip.hidden = true;
sceneChip.onclick = () => openTab('friday'); sceneChip.title = 'Show the active scene';
const command = el('input', 'command');
command.placeholder = 'A thought, a command…'; command.autocomplete = 'off'; command.spellcheck = false; command.maxLength = 4000;
command.setAttribute('aria-label', 'FRIDAY command'); command.setAttribute('role', 'combobox');
command.setAttribute('aria-autocomplete', 'list'); command.setAttribute('aria-controls', 'suggestions'); command.setAttribute('aria-expanded', 'false');
const pins = el('div', 'pins');
const projectsButton = button('Projects', 'projects', () => openTab('projects'));
const fridayButton = button('FRIDAY', 'app', () => openTab('friday'));
const settingsButton = button('Settings', 'settings', () => openTab('settings'));
const closeButton = button('Close · Esc', 'close', () => dispatch('escape'));
const tools = el('div', 'tools'); tools.append(pins, fridayButton, projectsButton, settingsButton, closeButton);
row.append(capsule.left, orb, capsule.right, live, sceneChip, command, tools);
const results = el('div', 'suggestions'); results.id = 'suggestions'; results.setAttribute('role', 'listbox');
const body = el('div', 'expanded-body');
const sneakReply = el('div', 'sneak-reply'); sneakReply.hidden = true; sneakReply.setAttribute('role', 'status');
const tabs = el('nav', 'tabs'); tabs.setAttribute('aria-label', 'Island tabs');
const panels = el('div', 'panels');
const expandedInner = el('div', 'expanded-inner'); expandedInner.append(tabs, panels);
body.append(expandedInner); surface.append(row, capsule.media, results, sneakReply, body);
const feedback = el('div', 'feedback'); feedback.hidden = true; feedback.setAttribute('role', 'status');
root.append(surface, feedback);

let config: Config = previewConfig();
let mode: Mode = sneakEnabled ? 'hidden' : 'rest';
let tab: Tab = 'projects';
let connection: Connection;
let online = false;
let integrated = false;
let snippet = '';
let schedule = '';
let reminder: PillSnippet | null = null;
let manifests: Manifest[] = [];
let nativeStatus: NativeStatus = { mode: 'rest', hotkey_errors: [], max_width: 720, max_height: 560, reduce_motion: false };
let suggestions: Suggestion[] = [];
let selected = -1;
let completed: Suggestion | undefined;
let busy = false;
let interaction = 0;
let active = false;
let lastActivity = Date.now();
let appliedIdleMode: Config['appearance']['idle_mode'] | undefined;
let leaveTimer: ReturnType<typeof setTimeout>;
let suggestionTimer: ReturnType<typeof setTimeout>;
let moodTimer: ReturnType<typeof setTimeout>;
let feedbackTimer: ReturnType<typeof setTimeout>;
let suggestionGeneration = 0;
const icons = new Map<string, string>();
const replies = new ReplySurface(surface, {
  mode: () => mode, sneak: () => sneakEnabled,
  available: () => !active && !command.value && mode !== 'expanded',
  reveal: () => setMode('rest'), restore: () => busy ? Promise.resolve() : setMode(config.appearance.idle_mode === 'hover' ? 'hidden' : 'rest'),
  changed: () => animateRegions(),
  action: async value => { const result = await connection.request('runtime_action', { action: 'notification', value }); return { ok: result.ok === true, text: String(result.text ?? '') }; },
  pluginAction: async (owner, id, payload) => {
    const result = await connection.pluginRequest(`${owner}/actions/${id}`, 'POST', payload);
    return { ok: result.ok === true, text: String(result.text ?? '') };
  },
  pluginGet: path => connection.pluginRequest(path),
});
row.append(replies.node);
const apps = new Apps(next => { config = next; applyConfig(); settings.refreshFavourites(); }, message);
const settings = new Settings(panels, {
  config: () => config, status: () => nativeStatus, online: () => online, message,
  apps,
  pluginRequest: (path, method, body) => connection.pluginRequest(path, method, body),
  restart: () => integrated && online ? connection.request('runtime_action', { action: 'restart' }) : call('start_friday'),
  reload: async () => { config = await call<Config>('reload_config'); applyConfig(); connect(); },
  save: async next => {
    const previous = config.connection;
    config = await call<Config>('save_config', { next });
    applyConfig();
    if (previous.port !== config.connection.port || previous.token !== config.connection.token) connect();
  },
});
const widgets = new PluginWidgets(panels, () => connection, result => { message(result.text, !result.ok); if (result.ok) mood('happy', 850); });
const friday = new FridayPanel(() => connection, text => run(text), message, event => replies.event(event), () => setMode('rest'));
const hud = new HudController(() => connection, message, () => config.island?.reduced_motion === true);
const mochi = new MochiDisplay(surface, orb, {
  config: () => config, status: () => nativeStatus, mode: () => mode,
  available: () => !sneakEnabled && !active && !busy && !command.value && !replies.visible && (mode === 'rest' || mode === 'peek'),
  peek: () => setMode('peek'), restore: () => setMode('rest'), refresh: () => mood(), layout: animateRegions,
});
const startupAnimation = new BootAnimation(surface, () => config, () => mochi.reduced, next => { config = next; });

function message(text: string, bad = false) {
  if (mode === 'sneak') { sneakReply.textContent = text; sneakReply.hidden = false; sneakReply.classList.toggle('bad', bad); }
  else if (mode === 'peek' || mode === 'expanded') {
    clearTimeout(feedbackTimer); feedback.textContent = text; feedback.classList.toggle('bad', bad); feedback.hidden = false;
    if (bad && text.includes('No app found')) {
      const rescan = el('button', 'text-button', 'Rescan apps'); rescan.onclick = () => void apps.rescan(); feedback.append(rescan);
    }
    feedbackTimer = setTimeout(() => { feedback.hidden = true; syncRegions(); }, bad ? 7000 : 3500);
  }
  else replies.offer({ text, kind: 'reply', bad }, true);
  if (bad) mood('error', 900);
  syncRegions();
}
function mood(value?: string, duration = 0) {
  clearTimeout(moodTimer);
  const state = friday.state?.body;
  if (state?.listening || state?.speaking || state?.thinking) {
    mochi.character.setMood(state.listening ? 'listening' : state.speaking ? 'speaking' : 'thinking'); mochi.comfort();
  } else mochi.update(value ?? (online ? 'idle' : 'offline'));
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
  next = sneakMode(next, sneakEnabled, activate, mode);
  clearTimeout(leaveTimer);
  lastActivity = Date.now();
  mode = next; active = activate && ['peek', 'expanded', 'sneak'].includes(next);
  surface.dataset.mode = next;
  root.dataset.mode = next;
  surface.dataset.active = String(active);
  capsule.setMode(next);
  command.placeholder = next === 'sneak' ? 'What would you like to do?' : 'A thought, a command…';
  if (next === 'rest' || next === 'hidden') { command.value = ''; clearSuggestions(); }
  if (next !== 'peek' && next !== 'expanded') { feedback.textContent = ''; feedback.hidden = true; }
  if (next !== 'expanded') friday.close();
  if (next !== 'sneak') { sneakReply.textContent = ''; sneakReply.hidden = true; }
  body.inert = next !== 'expanded';
  if (next !== 'expanded') widgets.hide();
  if (next === 'expanded') { clearSuggestions(); renderPanel(); }
  replies.sync(); mood(); animateRegions();
  try { if (native) await call('set_mode', { mode: next, activate: active }); if (active) command.focus(); }
  catch (error) { message(String(error), true); }
  replies.flush();
}
function dispatch(event: Parameters<typeof transition>[1], activate = false) {
  if (event === 'escape' || event === 'sneak') interaction++;
  if (event === 'sneak') {
    sneakEnabled = !sneakEnabled;
    try { localStorage.setItem('friday.sneak', String(sneakEnabled)); } catch { /* Keep the session toggle. */ }
    return setMode(sneakEnabled ? 'sneak' : config.appearance.idle_mode === 'hover' ? 'hidden' : 'rest', sneakEnabled);
  }
  if (event === 'escape' && replies.visible) { replies.dismiss(); return Promise.resolve(); }
  return setMode(transition(mode, event, config.appearance.idle_mode), activate);
}
async function openTab(next: Tab) { tab = next; await setMode('expanded', active); }
surface.onpointerenter = () => { lastActivity = Date.now(); clearTimeout(leaveTimer); };
surface.onpointermove = event => {
  if (mode !== 'rest' || replies.visible) return;
  const bounds = orb.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right) void dispatch('hover');
};
row.onclick = event => {
  if ((mode === 'rest' || mode === 'peek') && !active && !(event.target as Element).closest('.character,.capsule-reply,button,input,textarea,select,a')) void setMode('peek', true);
};
orb.addEventListener('click', () => { lastActivity = Date.now(); });
surface.onpointerleave = () => {
  lastActivity = Date.now();
  if (mode === 'peek' && !active && !command.value) leaveTimer = setTimeout(() => void dispatch('leave'), 400);
};
surface.addEventListener('pointerdown', event => {
  const target = event.target as HTMLElement;
  if (!target.closest('input,textarea,select') || active) return;
  event.preventDefault();
  active = true;
  void call('set_mode', { mode, activate: true }).then(() => target.focus()).catch(error => message(String(error), true));
});
window.addEventListener('blur', () => {
  active = false;
  if (native) void call('clear_execution_target').catch(() => {});
  if (mode === 'peek' || mode === 'sneak') void dispatch('escape');
  else if (mode === 'rest') replies.resolvePrivate();
});
window.addEventListener('keydown', event => { if (matchesDismiss(event, config.hotkeys.dismiss)) { event.preventDefault(); if (!event.repeat) void dispatch('escape'); } });

function applyConfig() {
  mochi.comfort();
  document.documentElement.style.setProperty('--accent', config.appearance.glow);
  document.documentElement.style.setProperty('--orb-edge', `color-mix(in srgb, ${config.appearance.glow}, #b65018 45%)`);
  root.classList.toggle('character-only', !config.appearance.snippet);
  renderPins(); updateLive();
  if (appliedIdleMode !== config.appearance.idle_mode) {
    appliedIdleMode = config.appearance.idle_mode;
    if (mode === 'rest' || mode === 'hidden') {
      const next = appliedIdleMode === 'hover' ? 'hidden' : 'rest';
      if (next !== mode) void setMode(next);
    }
  }
}
function updateLive() {
  if (online && config.appearance.snippet) replies.snippet(readReminder(reminder));
  capsule.setSchedule(online ? schedule : '');
  live.textContent = online ? snippet : 'FRIDAY offline';
  root.classList.toggle('character-only', !config.appearance.snippet || (online && !snippet.trim()));
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
  widgets.hide();
  tabs.replaceChildren();
  for (const id of ['friday', 'projects', 'plugins', 'settings'] as const) {
    const node = el('button', tab === id ? 'selected' : '', id === 'friday' ? 'FRIDAY' : id[0].toUpperCase() + id.slice(1));
    node.onclick = () => { tab = id; renderPanel(); }; tabs.append(node);
  }
  panels.replaceChildren();
  if (tab === 'friday') { friday.mount(panels); return; }
  friday.close();
  if (tab === 'settings') { settings.render(); return; }
  if (tab === 'plugins') {
    if (!online) panels.append(el('p', 'empty', 'Connect FRIDAY to see your plugins.'));
    else widgets.show(manifests);
    return;
  }
  const extras = config.pins.filter(p => p.visible).slice(pinLimit());
  if (extras.length) { const tray = el('div', 'extra-pins'); tray.append(...extras.map(pinButton)); panels.append(tray); }
  const heading = el('div', 'panel-heading'); heading.append(el('span', 'muted', 'A place for every idea'), button('Add project', 'plus', () => { tab = 'settings'; renderPanel(); return settings.addProject(); }));
  panels.append(heading);
  if (integrated && online) { sharedProjects(panels, connection, text => run(text), message, perform); return; }
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
  results.classList.toggle('slash-list', command.value.trimStart().startsWith('/'));
  if (selected >= 0) results.children[selected]?.scrollIntoView({ block: 'nearest' });
  surface.style.setProperty('--results-height', `${results.hidden ? 0 : results.offsetHeight}px`);
  syncRegions();
}
function clearSuggestions(keepCompletion = false) {
  clearTimeout(suggestionTimer); ++suggestionGeneration;
  if (!keepCompletion) completed = undefined;
  selected = -1; suggestions = []; renderSuggestions();
}
command.oninput = () => {
  sneakReply.textContent = ''; sneakReply.hidden = true;
  completed = undefined;
  lastActivity = Date.now(); mood();
  clearTimeout(suggestionTimer);
  const generation = ++suggestionGeneration;
  const text = command.value;
  selected = -1;
  if (text.trimStart().startsWith('/')) { suggestions = slashSuggestions(text, manifests, online ? integrated ? 'full' : 'standalone' : 'offline'); renderSuggestions(); return; }
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
  return head.startsWith('\\') || ['proj', 'settings', 'next', 'habit', 'todo', 'note', 'focus', ...manifests.flatMap(m => m.commands)].includes(head);
}
command.onkeydown = event => {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault(); selected = suggestions.length ? (selected + (event.key === 'ArrowDown' ? 1 : -1) + suggestions.length) % suggestions.length : -1; renderSuggestions();
  } else if (event.key === 'Tab' && suggestions.length) {
    event.preventDefault();
    const item = suggestions[Math.max(selected, 0)];
    if (item.rescan) { void run(item.text, item); return; }
    completed = item.fill ? undefined : item; command.value = item.text; clearSuggestions(true);
  } else if (event.key === 'Enter') { event.preventDefault(); const item = suggestions[selected] ?? (completed?.text === command.value ? completed : undefined); void run(item?.text ?? command.value, item); }
};
async function perform(result: CommandResult) {
  if (!result.ok) { message(result.text, true); return; }
  const action = result.action;
  if (action?.kind === 'app_search') { await perform(await call<CommandResult>('local_command', { text: `open ${action.query ?? ''}` })); return; }
  if (action?.kind === 'settings') {
    if (sneakEnabled) { await setMode('sneak', true); message('Turn off Sneak mode to open Island settings.'); }
    else { tab = 'settings'; await setMode('expanded', active); }
    return;
  }
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
  if (item?.fill) { command.value = item.text; clearSuggestions(); command.focus(); return; }
  if (item?.rescan) { await apps.rescan(); command.oninput?.(new Event('input')); return; }
  if (busy || !text.trim()) return;
  const fromSlash = text.trimStart().startsWith('/');
  try {
    const resolved = resolveSlash(text, manifests, online ? integrated ? 'full' : 'standalone' : 'offline');
    if (resolved.palette) { command.value = '/'; command.oninput?.(new Event('input')); return; }
    if (resolved.view) { if (sneakEnabled) message('Turn off Sneak mode to open Island panels.'); else await openTab(resolved.view); return; }
    text = resolved.text;
  } catch (error) { message(String(error), true); return; }
  const generation = interaction;
  busy = true; command.disabled = true;
  const sneak = mode === 'sneak';
  const targetWindow = native ? await call<ExecutionTarget | null>('execution_target').catch(() => null) : null;
  if (sneak) await setMode('hidden');
  else { replies.begin(); await setMode('rest'); }
  try {
    let result: CommandResult;
    const feature = integrated && (isFileReference(text) || /^(?:open (?:college schedules|habits|productivity|friday settings)|settings friday)(?:\s|$)/i.test(text.trim()));
    const nativeText = fromSlash && text.startsWith('\\o ') ? `open ${text.slice(3)}` : text;
    const local = native && !feature && /^(?:open|proj|settings)(?:\s|$)/i.test(nativeText.trim());
    const exact = !fromSlash && !item?.app && !feature && !local && native && !isBrainCommand(text) ? (await apps.search(text, 1).catch(() => [])).find(a => a.name.toLowerCase() === text.trim().toLowerCase()) : undefined;
    const target = item?.app ?? exact;
    if (target) result = { ok: true, text: `Opening ${target.name}`, action: { kind: target.kind, id: target.id } };
    else {
      if (integrated && !local && !target) await setMode('rest');
      result = local ? await call<CommandResult>('local_command', { text: nativeText }) : online ? await connection.command(text, targetWindow ?? undefined) : native ? await call<CommandResult>('local_command', { text: nativeText })
      : { text: 'Desktop commands are available in the Tauri app.', ok: false };
      if (local && !result.ok && integrated && /^(?:proj|open)\s/i.test(nativeText)) {
        await setMode('rest');
        result = await connection.command(/^proj\s/i.test(text) ? `resume ${text.trim().slice(5)}` : text, targetWindow ?? undefined);
      }
    }
    if (generation !== interaction && (!result.action || result.action.kind === 'settings')) { friday.close(); return; }
    if (integrated && !result.action) {
      if (result.keyboard_token) {
        await setMode('rest');
        try { const applied = await connection.request('keyboard_apply', { item: result.keyboard_token }); result.text = String(applied.text); result.ok = applied.ok === true; }
        catch (error) { result.ok = false; result.text = String(error); }
      }
      friday.accept(text, result);
      if (!result.keyboard_token) {
        if (result.model === 'briefings' && !sneakEnabled) await openTab('friday');
        else if (sneakEnabled) { await setMode('sneak'); message(result.text, !result.ok); }
        else replies.result(result);
      } else if (sneakEnabled) message(result.text, !result.ok); else replies.result(result);
    } else {
      if (sneakEnabled && !result.action) await setMode('sneak');
      else if (!sneakEnabled && result.model === 'briefings') await openTab('friday');
      else if (!sneakEnabled && result.action?.kind !== 'settings') await setMode('rest');
      await perform(result);
    }
    if (result.ok && mode === 'expanded' && tab === 'plugins') void widgets.refresh();
    command.value = ''; clearSuggestions();
  } catch (error) { if (generation === interaction) { await setMode(sneakEnabled ? 'sneak' : 'rest'); message(String(error), true); } }
  finally { busy = false; replies.finish(); command.disabled = false; if (active) command.focus(); }
}
function connect() {
  connection?.stop();
  friday.connected(false);
  online = false; integrated = false; manifests = []; snippet = ''; schedule = ''; reminder = null; updateLive();
  sceneState.reset(); paintScene();
  sceneCardVersion++;
  connection = new Connection(config.connection, frame => {
    if (frame.type === 'bus_event' && frame.event && typeof frame.event === 'object') {
      const event = frame.event as Record<string, unknown>;
      hud.event(event);
      if (event.topic === 'todo.changed') void widgets.refresh();
      mochi.receive(event);
      if (sceneState.event(event)) {
        paintScene();
        if (event.topic === 'scene.started' || event.topic === 'scene.ended') sceneCardVersion++;
      }
      if (briefingCard(event)) {
        friday.pluginEvent(event);
        if (!sneakEnabled) void openTab('friday');
      } else if (event.topic === 'ui.card' && event.plugin_id === 'scenes') {
        sceneCardVersion++;
        friday.pluginEvent(event); replies.pluginEvent(event);
        if (mode === 'expanded' && tab !== 'friday') openTab('friday');
      } else if (!replies.pluginEvent(event)) friday.pluginEvent(event);
      return;
    }
    if (frame.type === 'status') {
      const revision = sceneState.revision;
      const cardVersion = sceneCardVersion;
      void connection.pluginRequest('scenes/status').then(state => {
        if (sceneState.revision === revision) { sceneState.status(state); paintScene(); }
        if (sceneCardVersion === cardVersion && state.card && typeof state.card === 'object') {
          const event = { topic: 'ui.card', plugin_id: 'scenes', payload: state.card };
          friday.pluginEvent(event); replies.pluginEvent(event);
          if (mode === 'expanded' && tab !== 'friday') openTab('friday');
        }
      }).catch(() => { /* Scenes is an optional offline plugin. */ });
      void connection.pluginRequest('mood/state').then(payload => {
        if (!mochi.hasState) mochi.receive({ topic: 'mood.changed', payload });
      }).catch(() => {});
      void hud.refresh();
      if (native && frame.integrated !== true) void call('boot_done');
      const previous = integrated; integrated = frame.integrated === true;
      if (integrated && !previous) { tab = 'friday'; if (mode === 'expanded') renderPanel(); }
    }
    startupAnimation.receive(frame);
    if (friday.receive(frame)) { hud.scene(friday.state?.system.mode.name ?? ''); mood(); return; }
    if (frame.type === 'pill_snippet_update' && typeof frame.text === 'string') {
      schedule = typeof frame.schedule === 'string' ? frame.schedule.slice(0, 100) : '';
      widgets.updateCollege(frame.college_text);
      snippet = frame.text.slice(0, 80); reminder = readReminder(frame); updateLive();
    }
    if (frame.type === 'plugin_list' && Array.isArray(frame.plugins)) {
      manifests = frame.plugins.filter((m): m is Manifest => typeof m === 'object' && m !== null && typeof m.id === 'string' && typeof m.name === 'string' && Array.isArray(m.commands));
      if (mode === 'expanded' && tab === 'plugins') renderPanel();
    }
    if (['status', 'plugin_list'].includes(frame.type) && command.value.trimStart().startsWith('/')) command.oninput?.(new Event('input'));
  }, connected => {
    online = connected;
    if (!connected) { mochi.reset(); sceneState.reset(); paintScene(); sceneCardVersion++; }
    hud.online(connected);
    friday.connected(connected);
    settings.connectionChanged();
    if (!connected) { manifests = []; snippet = ''; schedule = ''; reminder = null; sneakReply.textContent = ''; sneakReply.hidden = true; replies.clear(); }
    if (command.value.trimStart().startsWith('/')) command.oninput?.(new Event('input'));
    updateLive();
    if (mode === 'expanded' && tab === 'plugins') renderPanel();
  });
  if (native) connection.start();
}
function paintScene() {
  surface.dataset.scene = sceneState.name ? 'true' : 'false';
  sceneChip.textContent = sceneState.name ? `${sceneState.name} mode` : '';
  sceneChip.hidden = !sceneState.name;
  sceneChip.setAttribute('aria-label', sceneState.name ? `Active scene: ${sceneState.name}. Show controls.` : 'No active scene');
  queueMicrotask(syncRegions);
}
async function boot() {
  try { if (native) { const initial = await startupState(); config = initial.config; nativeStatus = initial.status; } }
  catch (error) { message(String(error), true); }
  await hud.start(); await startupAnimation.start();
  applyConfig(); await setMode(mode); connect();
  if (nativeStatus.hotkey_errors.length) message(`Hotkey registration failed: ${nativeStatus.hotkey_errors.join(' ')} Open Settings → Hotkeys.`, true);
  capsule.setMode(mode);
  await apps.start(() => { icons.clear(); renderPins(); if (mode === 'expanded' && tab === 'settings' && settings.section === 'apps') settings.render(); });
  applyLimits();
  mochi.comfort();
  await on<string>('hotkey', event => { if (event === 'sneak' || event === 'expand' || event === 'escape') void dispatch(event, event !== 'escape'); });
  await on<NativeStatus>('native-status', status => {
    if (status.hotkey_errors.length && JSON.stringify(status.hotkey_errors) !== JSON.stringify(nativeStatus.hotkey_errors))
      message(`Hotkey registration failed: ${status.hotkey_errors.join(' ')} Open Settings → Hotkeys.`, true);
    nativeStatus = status; applyLimits(); mochi.comfort();
    if (mode === 'expanded' && tab === 'settings' && settings.section === 'hotkeys') settings.render();
  });
  await on<{ x: number; y: number; reveal: boolean }>('pointer', point => {
    if (sneakEnabled) return;
    if (point.reveal && mode === 'hidden') void dispatch('hover');
    if (!mochi.character.motionAllowed) return;
    if (mode === 'hidden' || mode === 'sneak') return;
    const bounds = orb.getBoundingClientRect();
    orb.style.setProperty('--eye-x', `${Math.max(-3, Math.min(3, (point.x - bounds.x - bounds.width / 2) / 90))}px`);
    orb.style.setProperty('--eye-y', `${Math.max(-2, Math.min(2, (point.y - bounds.y - bounds.height / 2) / 90))}px`);
  });
  setInterval(() => {
    if (config.appearance.idle_mode === 'auto-hide' && !busy && !replies.visible && !active && !command.value && !surface.matches(':hover') && mode === 'rest' && Date.now() - lastActivity > config.appearance.idle_seconds * 1000) void dispatch('idle');
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
