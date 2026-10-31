export type Mode = 'rest' | 'peek' | 'expanded' | 'sneak' | 'hidden';
export type Tab = 'projects' | 'plugins' | 'settings';
export interface Pin { id: string; name: string; path: string; visible: boolean; app_id?: string | null }
export interface AppMatch { id: string; name: string; source: string; kind: 'app' | 'pin'; pinned: boolean }
export interface IndexStatus { count: number; scanning: boolean; updated_at: number; errors: string[] }
export type OpenAction = { kind: 'folder' } | { kind: 'editor' | 'terminal'; executable: string; args: string[] } | { kind: 'url'; url: string };
export interface Project { id: string; name: string; path: string; color: string; last_opened: string | null; actions: OpenAction[] }
export interface Config {
  source_stamp?: string;
  version: 1; revision: number; pins: Pin[]; projects: Project[];
  recent_apps: { id: string; last_used: number; count: number }[];
  hotkeys: { sneak: string; expand: string };
  appearance: { glow: string; idle_mode: 'always' | 'auto-hide' | 'hover'; idle_seconds: number; snippet: boolean };
  connection: { port: number; token: string };
}
export interface Suggestion { text: string; detail?: string; app?: AppMatch; rescan?: boolean }
export interface CommandResult { text: string; ok: boolean; action?: { kind: 'settings' | 'pin' | 'project' | 'app' | 'app_search'; id?: string; query?: string } }
export interface Manifest { id: string; name: string; version: number; commands: string[]; widget: boolean }
export interface Widget { title: string; text: string; placeholder?: boolean }
export interface NativeStatus { mode: string; hotkey_errors: string[]; max_width: number; max_height: number; reduce_motion: boolean }
export interface BatteryStatus { percent: number | null; charging: boolean; plugged_in: boolean | null }
export interface MediaSession {
  source: string; title: string; artist: string; playing: boolean;
  can_toggle: boolean; can_previous: boolean; can_next: boolean;
}
export interface DesktopStatus { battery: BatteryStatus | null; media: MediaSession | null }
