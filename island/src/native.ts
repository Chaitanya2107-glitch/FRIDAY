import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import type { Config, NativeStatus } from './types';

export const native = isTauri();
export const call = <T>(command: string, args: Record<string, unknown> = {}) => {
  if (!native) return Promise.reject(new Error('Open the Tauri app to use desktop controls.'));
  return invoke<T>(command, args);
};
export async function on<T>(event: string, handler: (value: T) => void) {
  if (native) await listen<T>(event, e => handler(e.payload));
}
export async function startupState() {
  for (let attempt = 0; ; attempt++) {
    try { return { config: await call<Config>('get_config'), status: await call<NativeStatus>('runtime_status') }; }
    catch (error) {
      if (attempt >= 19) throw error;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }
}
export const previewConfig = (): Config => ({
  version: 1, revision: 0, pins: [], projects: [], recent_apps: [],
  hotkeys: { sneak: 'Ctrl+Shift+S', expand: 'Ctrl+Shift+Alt+I', dismiss: 'Escape', hud: 'Ctrl+Shift+Alt+H' },
  island: { boot_animation: true, reduced_motion: false }, user_name: '',
  appearance: { glow: '#FFB347', idle_mode: 'always', idle_seconds: 30, snippet: true },
  connection: { port: 17321, api_port: 8000, token: '' },
  startup: { manage_bridge: true, backend_root: '', launch_at_login: false, start_with_friday: false },
});
