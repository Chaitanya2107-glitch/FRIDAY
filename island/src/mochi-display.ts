import './mochi.css';
import { Mochi, motionReduced, readMood, type MoodState } from './mochi';
import type { Config, Mode, NativeStatus } from './types';

interface Host {
  config: () => Config; status: () => NativeStatus; mode: () => Mode;
  available: () => boolean; peek: () => Promise<void>; restore: () => Promise<void>;
  refresh: () => void; layout: () => void;
}

/** Display only: the backend owns priority, sticky contexts and rule cooldowns. */
export class MochiDisplay {
  readonly character: Mochi;
  private state?: MoodState;
  private expiry?: ReturnType<typeof setTimeout>;
  private bubbleTimer?: ReturnType<typeof setTimeout>;
  private bubble = document.createElement('div');
  private media = matchMedia('(prefers-reduced-motion: reduce)');
  private autoPeek = false;
  constructor(private surface: HTMLElement, orb: HTMLElement, private host: Host) {
    this.character = new Mochi(surface, orb);
    this.bubble.className = 'mood-bubble'; this.bubble.hidden = true;
    this.bubble.setAttribute('role', 'status'); this.bubble.setAttribute('aria-live', 'polite');
    surface.insertBefore(this.bubble, surface.children[1] ?? null);
    this.media.addEventListener('change', () => this.comfort());
    document.addEventListener('visibilitychange', () => this.comfort());
    window.addEventListener('pagehide', () => this.close());
  }
  get reduced() { return motionReduced(this.host.config().island?.reduced_motion, this.host.status().reduce_motion, this.media.matches); }
  get hasState() { return this.state !== undefined; }
  private paused() {
    const status = this.host.status(), mode = this.host.mode();
    return document.hidden || mode === 'hidden' || mode === 'sneak'
      || this.surface.dataset.mode === 'hidden' || this.surface.dataset.mode === 'sneak'
      || status.fullscreen_front === true || status.desktop_locked === true;
  }
  comfort() {
    document.documentElement.classList.toggle('reduce-motion', this.reduced);
    this.character.comfort(this.reduced, this.paused());
  }
  update(fallback: string) {
    const state = this.state;
    const valid = state && (state.until === null || state.until > Date.now());
    this.character.setMood(valid && (state.mood !== 'idle' || state.until !== null) ? state.mood : fallback);
    this.comfort();
  }
  receive(event: Record<string, unknown>) {
    if (event.topic !== 'mood.changed') return;
    const state = readMood(event.payload);
    if (!state) return;
    this.state = state;
    clearTimeout(this.expiry);
    if (state.until !== null) this.expiry = setTimeout(() => this.host.refresh(), Math.max(0, state.until - Date.now()));
    this.host.refresh();
    if (this.surface.dataset.mood === state.mood) this.character.replay();
    if (state.message) this.showMessage(state.message);
  }
  private showMessage(text: string) {
    clearTimeout(this.bubbleTimer);
    this.bubble.textContent = text; this.bubble.hidden = false;
    if (!this.paused() && this.host.mode() === 'rest' && this.host.available()) {
      this.autoPeek = true;
      void this.host.peek();
    }
    this.host.layout();
    this.bubbleTimer = setTimeout(() => {
      this.bubble.hidden = true;
      if (this.autoPeek && this.host.mode() === 'peek' && this.host.available()) void this.host.restore();
      this.autoPeek = false; this.host.layout();
    }, 4000);
  }
  reset() {
    this.state = undefined; this.autoPeek = false;
    clearTimeout(this.expiry); clearTimeout(this.bubbleTimer);
    this.bubble.hidden = true; this.host.layout();
  }
  close() { this.reset(); this.character.close(); }
}
