import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import type { Config } from './types';

export const native = isTauri();
export const call = <T>(command: string, args: Record<string, unknown> = {}) => {
  if (!native) return Promise.reject(new Error('Open the Tauri app to use desktop controls.'));
  return invoke<T>(command, args);
};
export async function on<T>(event: string, handler: (value: T) => void) {
  if (native) await listen<T>(event, e => handler(e.payload));
}
export const previewConfig = (): Config => ({
  version: 1, revision: 0, pins: [], projects: [],
  hotkeys: { sneak: 'Ctrl+Shift+Alt+Space', expand: 'Ctrl+Shift+Alt+F' },
  appearance: { glow: '#FFB347', idle_mode: 'always', idle_seconds: 30, snippet: true },
  connection: { port: 17321, token: '' },
});
