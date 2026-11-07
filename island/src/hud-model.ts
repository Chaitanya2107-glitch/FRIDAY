export interface HudSettings {
  enabled: boolean; editing: boolean; layer: 'desktop' | 'top'; monitor: string;
  x: number; y: number; width: number; height: number; opacity: number;
  hide_fullscreen: boolean; hide_game: boolean; saver: boolean; auto_saver: boolean; battery_threshold: number;
  widgets: Record<'system' | 'network' | 'clock' | 'class' | 'focus' | 'scene' | 'activity', boolean>;
}
export interface HudStats {
  sampled_at: number; cpu_percent: number | null;
  ram: { percent: number; used_bytes: number; total_bytes: number } | null;
  battery: { percent: number | null; plugged: boolean; charging: boolean } | null;
  gpu: { percent: number } | null;
  network: { upload_bps: number; download_bps: number } | null;
}
export interface HudState {
  settings: HudSettings; scene: string; game: boolean; fullscreen: boolean;
  focus: { session_id: string; duration_s: number; ends_at: number | null; remaining_s: number | null } | null;
  next_class: { subject: string; faculty: string; room: string; starts_at: string } | null;
  activity: Record<string, number> | null;
}
export interface HudStatus { visible: boolean; editing: boolean; reason: string; reduce_motion: boolean }
export interface HudFrame { state: HudState; stats: HudStats | null; saver: boolean; now: number; error: boolean; reduced_motion?: boolean }
export function saving(settings: HudSettings, stats: HudStats | null) {
  const battery = stats?.battery;
  return settings.saver || !!(settings.auto_saver && battery && !battery.plugged && battery.percent !== null && battery.percent < settings.battery_threshold);
}
export function remaining(focus: HudState['focus'], now: number) {
  return focus ? Math.max(0, focus.remaining_s ?? ((focus.ends_at ?? now) - now)) : 0;
}
export function duration(seconds: number) {
  const minutes = Math.ceil(Math.max(0, seconds) / 60);
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
/** No overlapping polls; hiding aborts in-flight work and fences late responses. */
export class HudPoller {
  private timer?: ReturnType<typeof setTimeout>;
  private abort?: AbortController;
  private generation = 0;
  private active = false;
  private interval = 1000;
  private read: (signal: AbortSignal) => Promise<unknown>;
  private receive: (value: unknown) => number;
  private failed: () => void;
  constructor(read: (signal: AbortSignal) => Promise<unknown>, receive: (value: unknown) => number, failed: () => void = () => {}) {
    this.read = read; this.receive = receive; this.failed = failed;
  }
  show(interval = 1000) { this.stop(); this.active = true; this.interval = interval; void this.poll(this.generation); }
  stop() { this.active = false; ++this.generation; clearTimeout(this.timer); this.abort?.abort(); }
  private async poll(generation: number) {
    const controller = this.abort = new AbortController();
    const started = Date.now();
    const timeout = setTimeout(() => controller.abort(), 4000);
    try { const value = await this.read(controller.signal); if (this.active && generation === this.generation) this.interval = this.receive(value); }
    catch { if (this.active && generation === this.generation) this.failed(); }
    finally {
      clearTimeout(timeout);
      if (this.active && generation === this.generation) this.timer = setTimeout(() => void this.poll(generation), Math.max(20, this.interval - (Date.now() - started)));
    }
  }
}
