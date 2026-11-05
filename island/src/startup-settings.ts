import { call, native } from './native';
import { element as el } from './state';
import type { Config, StartupStatus } from './types';

export function startupSettings(config: Config, save: (next: Config) => Promise<unknown>, reload: () => Promise<void>, message: (text: string, bad?: boolean) => void, restartFriday?: () => Promise<unknown>) {
  const box = el('div', 'startup-settings');
  const prefs = config.startup ?? { manage_bridge: true, backend_root: '', launch_at_login: false };
  function field(label: string, control: HTMLElement) {
    const row = el('label', 'field'); row.append(el('span', 'field-label', label), control); box.append(row);
  }
  function action(label: string, run: () => Promise<unknown>) {
    const button = el('button', 'text-button', label); button.type = 'button';
    button.onclick = () => void run().catch(error => message(String(error), true));
    box.append(button); return button;
  }
  const manage = el('input'); manage.type = 'checkbox'; manage.checked = prefs.manage_bridge;
  field('Start FRIDAY when Island opens', manage);
  manage.onchange = () => {
    const next = structuredClone(config); next.startup = { ...prefs, manage_bridge: manage.checked };
    void save(next);
  };
  const together = el('input'); together.type = 'checkbox'; together.checked = prefs.start_with_friday === true;
  field('Start Island together with FRIDAY', together);
  together.onchange = () => {
    const next = structuredClone(config); next.startup = { ...prefs, start_with_friday: together.checked };
    void save(next);
  };
  action('Choose FRIDAY folder', async () => {
    const picked = await call<{ path: string } | null>('choose_path', { folder: true });
    if (picked) { const next = structuredClone(config); next.startup = { ...prefs, backend_root: picked.path }; await save(next); }
  });
  box.append(el('p', 'muted', prefs.backend_root || 'FRIDAY folder is detected automatically.'));
  const status = el('p', 'muted', native ? 'Checking bridge startup…' : 'Startup controls require the desktop app.');
  const error = el('p', 'error-text'); box.append(status, error);
  const login = el('input'); login.type = 'checkbox'; login.checked = false; login.disabled = true;
  login.setAttribute('aria-label', 'Launch Island at Windows sign-in');
  field('Launch FRIDAY at Windows sign-in', login);
  let loginBusy = false;
  login.onchange = async () => {
    if (loginBusy) return;
    loginBusy = true;
    login.disabled = true;
    try { await call('set_login', { enabled: login.checked }); await reload(); message('Sign-in startup updated'); }
    catch (failure) { message(String(failure), true); }
    finally { loginBusy = false; void poll(); }
  };
  const restart = action('Restart FRIDAY', () => restartFriday ? restartFriday() : call('restart_bridge')); restart.disabled = true;
  box.append(el('small', 'muted', 'FRIDAY owns the backend lifecycle. Manually started backends keep their own ownership.'));
  let timer: ReturnType<typeof setTimeout>;
  const poll = async () => {
    clearTimeout(timer);
    if (!native || !box.isConnected) return;
    try {
      const state = await call<StartupStatus>('startup_status');
      if (!box.isConnected) return;
      const labels: Record<string,string> = { managed: 'Bridge managed by Island', external: 'Existing server detected; authentication is checked separately', starting: 'Starting FRIDAY bridge…', retrying: 'Waiting to retry the bridge…', disabled: 'Automatic bridge launch is off', error: 'Bridge needs attention' };
      status.textContent = labels[state.phase] ?? 'Checking bridge…'; error.textContent = state.error;
      if (!loginBusy) login.checked = state.login_enabled;
      login.disabled = state.isolated || loginBusy; restart.disabled = state.isolated || (!restartFriday && !state.owned_pid);
    } catch { status.textContent = 'Startup status unavailable.'; }
    if (box.isConnected) timer = setTimeout(() => void poll(), 2000);
  };
  // Mount first so polling stops naturally when Settings is removed.
  setTimeout(() => void poll(), 0);
  return box;
}
