export type Mode = 'rest' | 'peek' | 'expanded' | 'sneak' | 'hidden';
export type Tab = 'projects' | 'plugins' | 'settings';
export interface Pin { id: string; name: string; path: string; visible: boolean }
export type OpenAction = { kind: 'folder' } | { kind: 'editor' | 'terminal'; executable: string; args: string[] } | { kind: 'url'; url: string };
export interface Project { id: string; name: string; path: string; color: string; last_opened: string | null; actions: OpenAction[] }
export interface Config {
  source_stamp?: string;
  version: 1; revision: number; pins: Pin[]; projects: Project[];
  hotkeys: { sneak: string; expand: string };
  appearance: { glow: string; idle_mode: 'always' | 'auto-hide' | 'hover'; idle_seconds: number; snippet: boolean };
  connection: { port: number; token: string };
}
export interface Suggestion { text: string; detail?: string }
export interface CommandResult { text: string; ok: boolean; action?: { kind: 'settings' | 'pin' | 'project'; id?: string } }
export interface Manifest { id: string; name: string; version: number; commands: string[]; widget: boolean }
export interface Widget { title: string; text: string; placeholder?: boolean }
export interface NativeStatus { mode: string; hotkey_errors: string[]; acrylic: boolean; reduce_motion: boolean }
