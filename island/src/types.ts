export type Mode = 'rest' | 'peek' | 'expanded' | 'sneak' | 'hidden';
export type Tab = 'friday' | 'projects' | 'plugins' | 'settings';
export interface Pin { id: string; name: string; path: string; visible: boolean; app_id?: string | null }
export interface AppMatch { id: string; name: string; source: string; kind: 'app' | 'pin'; pinned: boolean }
export interface IndexStatus { count: number; scanning: boolean; updated_at: number; errors: string[] }
export type OpenAction = { kind: 'folder' } | { kind: 'editor' | 'terminal'; executable: string; args: string[] } | { kind: 'url'; url: string };
export interface Project { id: string; name: string; path: string; color: string; last_opened: string | null; actions: OpenAction[] }
export interface Config {
  source_stamp?: string;
  version: 1; revision: number; pins: Pin[]; projects: Project[];
  recent_apps: { id: string; last_used: number; count: number }[];
  hotkeys: { sneak: string; expand: string; dismiss?: string; hud?: string };
  island?: { boot_animation: boolean; last_boot_epoch?: string; reduced_motion?: boolean };
  user_name?: string;
  appearance: { glow: string; idle_mode: 'always' | 'auto-hide' | 'hover'; idle_seconds: number; snippet: boolean };
  connection: { port: number; token: string; api_port?: number };
  startup?: { manage_bridge: boolean; backend_root: string; launch_at_login: boolean; start_with_friday?: boolean };
}
export interface StartupStatus { phase: string; error: string; owned_pid: number | null; attempts: number; isolated: boolean; login_enabled: boolean }
export interface Suggestion { text: string; detail?: string; app?: AppMatch; rescan?: boolean; fill?: boolean }
export interface CommandResult {
  text: string; ok: boolean; private?: boolean; awaiting_reply?: boolean;
  keyboard_token?: string; automation_job?: string | null; provider?: string; model?: string;
  action_success?: boolean | null;
  action?: { kind: 'settings' | 'pin' | 'project' | 'app' | 'app_search'; id?: string; query?: string };
}
export interface ExecutionTarget { hwnd: number; pid: number; captured_at: number }
export interface FridayState {
  backend: boolean; epoch: string; last: number; provider: string;
  body: { listening: boolean; thinking: boolean; speaking: boolean };
  desktop: { connected: boolean; listening: boolean; wake: boolean; conversation: boolean; speak: boolean; speak_typed: boolean; body: boolean; owned: boolean; provider?: string | null; message: string };
  system: { mode: { name: string | null }; screen_watch: { state?: string; enabled?: boolean; paused?: boolean } };
  automation: { active: boolean; job_id?: string | null; state?: string; response?: string; awaiting_reply?: boolean };
  events: { id: number; kind: string; text: string; title: string; at: number; buttons: [string, string][]; awaiting_reply?: boolean; transient?: boolean }[];
}
export interface Manifest { id: string; name: string; version: number; commands: string[]; widget: boolean }
export interface PluginAction { action: string; item?: string; value?: string; revision?: number | null }
export interface WidgetAction extends PluginAction { label: string; disabled?: boolean }
export interface Widget {
  title: string; text: string; placeholder?: boolean;
  items?: { id: string; label: string; detail: string; action?: WidgetAction }[];
  input?: { label: string; placeholder: string; action: string; max_length: number };
}
export interface PillSnippet { text: string; show_from: number; expires_at: number }
export interface NativeStatus { mode: string; hotkey_errors: string[]; max_width: number; max_height: number; reduce_motion: boolean; fullscreen_front?: boolean; desktop_locked?: boolean }
export interface BatteryStatus { percent: number | null; charging: boolean; plugged_in: boolean | null }
export interface MediaSession {
  source: string; title: string; artist: string; playing: boolean;
  can_toggle: boolean; can_previous: boolean; can_next: boolean;
}
export interface DesktopStatus { battery: BatteryStatus | null; media: MediaSession | null }
