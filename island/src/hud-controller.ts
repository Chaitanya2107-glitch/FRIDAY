import { call, native, on } from './native';
import type { Connection } from './connection';
import { HudPoller, saving, type HudSettings, type HudState, type HudStats, type HudStatus } from './hud-model';

/** Main Island is the only bridge client. The HUD receives small native frames. */
export class HudController {
  private state?: HudState;
  private stats: HudStats | null = null;
  private visible = false;
  private connected = false;
  private signature = '';
  private slow?: ReturnType<typeof setTimeout>;
  private legacyScene = '';
  private syncing?: Promise<void>;
  private dirty = false;
  private generation = 0;
  private poller = new HudPoller(signal => this.connection().pluginRequest('hud/stats', 'GET', undefined, signal), value => {
    this.stats = value as unknown as HudStats; void this.paint(false);
    return this.state && saving(this.state.settings, this.stats) ? 5000 : 1000;
  }, () => { void this.paint(true); });
  constructor(private connection: () => Connection, private message: (text: string, bad?: boolean) => void,
              private reduced: () => boolean = () => false) {}
  async start() {
    await on<HudStatus>('hud-status', status => {
      const changed = this.visible !== status.visible;
      this.visible = status.visible;
      if (!status.visible) { this.poller.stop(); clearTimeout(this.slow); }
      else if (changed && this.connected) { this.poller.show(this.interval()); void this.refresh(); }
    });
    await on<string>('hotkey', key => { if (key === 'hud' && this.connected && this.state) void this.change({ enabled: !this.state.settings.enabled }); });
    await on('hud-done', () => { void this.done(); });
  }
  online(value: boolean) {
    ++this.generation;
    this.connected = value;
    this.poller.stop(); clearTimeout(this.slow);
    if (value) { this.signature = ''; void this.refresh(); }
    else if (this.state) { void call('hud_apply', { settings: { ...this.state.settings, enabled: false }, game: false, fullscreen: false }); }
  }
  event(event: Record<string, unknown>) {
    if (event.topic === 'hud.changed' && event.payload && typeof event.payload === 'object') {
      const payload = event.payload as { settings: HudSettings; action: string };
      if (payload.action === 'done') { void this.done(); return; }
      if (this.state && payload.settings) { this.state.settings = payload.settings; this.signature = ''; void this.apply(); }
      if (payload.action === 'saver on' || payload.action === 'saver off') { if (this.visible) this.poller.show(this.interval()); }
    }
    if (/^(?:hud\.(?:state_changed|available)|schedule\.|plugin\.disabled)/.test(String(event.topic))) void this.refresh();
  }
  scene(name: string) {
    if (name === this.legacyScene) return;
    this.legacyScene = name;
    if (this.state) { this.signature = ''; void this.apply(); }
  }
  refresh(): Promise<void> {
    if (this.syncing) { this.dirty = true; return this.syncing; }
    this.syncing = this.load().finally(() => { this.syncing = undefined; if (this.dirty) { this.dirty = false; void this.refresh(); } });
    return this.syncing;
  }
  private async load() {
    clearTimeout(this.slow);
    if (!native || !this.connected) return;
    const generation = this.generation;
    try {
      const state = await this.connection().pluginRequest('hud/state') as unknown as HudState;
      if (!this.connected || generation !== this.generation) return;
      this.state = state;
      await this.apply();
    } catch {
      if (!this.connected || generation !== this.generation) return;
      this.poller.stop();
      if (this.state) await call('hud_apply', { settings: { ...this.state.settings, enabled: false }, game: false, fullscreen: false }).catch(() => {});
    }
    if (this.connected && this.visible) this.slow = setTimeout(() => void this.refresh(), 30000);
  }
  private async apply() {
    if (!this.state) return;
    const scene = this.state.scene || this.legacyScene;
    const game = this.state.game || scene.toLowerCase() === 'game';
    const signature = JSON.stringify([this.state.settings, game, this.state.fullscreen]);
    if (signature !== this.signature) {
      const status = await call<HudStatus>('hud_apply', { settings: this.state.settings, game, fullscreen: this.state.fullscreen });
      this.signature = signature;
      if (status.visible && !this.visible) { this.visible = true; this.poller.show(this.interval()); }
    }
    await this.paint(false);
  }
  private interval() { return this.state && saving(this.state.settings, this.stats) ? 5000 : 1000; }
  private async paint(error: boolean) {
    if (this.state) await call('hud_data', { data: { state: { ...this.state, scene: this.state.scene || this.legacyScene },
      stats: this.stats, saver: saving(this.state.settings, this.stats), now: Date.now() / 1000, error, reduced_motion: this.reduced() } }).catch(() => {});
  }
  async change(changes: Partial<HudSettings>) {
    const result = await this.connection().pluginRequest('hud/actions/settings', 'POST', changes);
    if (!result.ok) throw Error(String(result.text));
    await this.refresh();
  }
  async done() {
    try {
      const geometry = await call<Record<string, unknown>>('hud_geometry');
      await this.change(geometry);
      this.message('HUD layout saved. Clicks pass through.');
    } catch (error) { this.message(`Could not save HUD layout: ${error}. Say hud done to retry.`, true); }
  }
}
