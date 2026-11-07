/** Quiet SVG poses. Timers run only during a reaction or an idle micro-behavior. */
export const MOODS = ['idle', 'happy', 'curious', 'worried', 'alarmed', 'sleepy', 'dozing',
  'focused', 'alert', 'celebrating', 'waving'] as const;
export type Mood = typeof MOODS[number];
export interface MoodState { mood: Mood; message: string; until: number | null; sticky: boolean }
export const FRAME_MS = 34; // At most 30 samples per second, even on 144 Hz displays.
export const randomDelay = (low: number, high: number, random = Math.random) => low + random() * (high - low);
export const motionReduced = (setting: boolean | undefined, windows: boolean, media: boolean) => !!setting || windows || media;

export function readMood(value: unknown, now = Date.now()): MoodState | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (!MOODS.includes(row.mood as Mood) || (row.message !== undefined && typeof row.message !== 'string')
      || (row.sticky !== undefined && typeof row.sticky !== 'boolean')) return null;
  const sticky = row.sticky === true;
  const deadline = row.until === undefined ? row.expires_at : row.until;
  if (deadline !== null && (typeof deadline !== 'number' || !Number.isFinite(deadline) || deadline < 0)) return null;
  if (sticky && deadline !== null && deadline !== 0) return null;
  const until = deadline === null || deadline === 0 ? null : deadline * 1000;
  if (!sticky && row.mood !== 'idle' && until === null) return null;
  if (until !== null && until <= now) return { mood: 'idle', message: '', until: null, sticky: false };
  return { mood: row.mood as Mood, message: Array.from(String(row.message ?? '')).slice(0, 60).join(''), until, sticky };
}

export class Mochi {
  private value = '';
  private reduced = false;
  private paused = true;
  private frame?: ReturnType<typeof setTimeout>;
  private blink?: ReturnType<typeof setTimeout>;
  private unblink?: ReturnType<typeof setTimeout>;
  private small?: ReturnType<typeof setTimeout>;
  private surface: HTMLElement;
  private orb: HTMLElement;
  constructor(surface: HTMLElement, orb: HTMLElement) {
    this.surface = surface; this.orb = orb;
  }
  get motionAllowed() { return !this.reduced && !this.paused; }
  setMood(value: string) {
    if (value === this.value) return;
    this.value = value;
    this.surface.dataset.mood = value;
    this.orb.setAttribute('aria-label', `Mochi, ${value}`);
    this.restart();
  }
  comfort(reduced: boolean, paused: boolean) {
    this.surface.dataset.motionPaused = String(paused);
    if (this.reduced === reduced && this.paused === paused) return;
    this.reduced = reduced; this.paused = paused;
    this.restart();
  }
  private stop() {
    for (const timer of [this.frame, this.blink, this.unblink, this.small]) clearTimeout(timer);
    this.frame = this.blink = this.unblink = this.small = undefined;
    delete this.orb.dataset.blink; delete this.orb.dataset.behavior;
    for (const key of ['y', 'tilt', 'sx', 'sy', 'pulse', 'hand', 'z', 'spark', 'look']) this.orb.style.removeProperty(`--mochi-${key}`);
  }
  private restart() {
    this.stop();
    if (!this.motionAllowed) return;
    if (this.value === 'idle') { this.scheduleBlink(); this.scheduleSmall(); return; }
    const duration = ({ happy: 900, curious: 800, worried: 900, alarmed: 850, sleepy: 5000,
      dozing: 6500, alert: 650, celebrating: 2400, waving: 1800 } as Record<string, number>)[this.value];
    if (duration) this.animate(duration, ['alarmed', 'sleepy', 'dozing'].includes(this.value));
  }
  private scheduleBlink() {
    this.blink = setTimeout(() => {
      this.orb.dataset.blink = 'true';
      this.unblink = setTimeout(() => { delete this.orb.dataset.blink; this.scheduleBlink(); }, 140);
    }, randomDelay(3000, 6000));
  }
  private scheduleSmall() {
    this.small = setTimeout(() => {
      const kind = ['look', 'stretch', 'yawn'][Math.floor(Math.random() * 3)];
      this.orb.dataset.behavior = kind;
      this.animate(1400, false, kind, () => { delete this.orb.dataset.behavior; this.scheduleSmall(); });
    }, randomDelay(20000, 60000));
  }
  private animate(duration: number, loop = false, kind = this.value, done = () => {}) {
    const start = performance.now();
    const interval = kind === 'dozing' || kind === 'sleepy' ? 250 : FRAME_MS;
    const set = (key: string, value: number, unit = '') => this.orb.style.setProperty(`--mochi-${key}`, value.toFixed(3) + unit);
    const tick = () => {
      if (!this.motionAllowed) return;
      const elapsed = performance.now() - start;
      const p = Math.min(1, (loop ? elapsed % duration : elapsed) / duration);
      const arc = Math.sin(Math.PI * p), wave = Math.sin(Math.PI * 2 * p);
      if (kind === 'happy' || kind === 'alert') set('y', -arc * (kind === 'alert' ? 3.5 : 2.5), 'px');
      if (kind === 'curious') set('tilt', arc * 3, 'deg');
      if (kind === 'worried') set('tilt', -arc * 2, 'deg');
      if (kind === 'alarmed') set('pulse', 1 + .35 * (1 - Math.cos(2 * Math.PI * p)));
      if (kind === 'sleepy') set('z', -arc * 5, 'px');
      if (kind === 'dozing' || kind === 'stretch') { set('sx', 1 + arc * .025); set('sy', 1 - arc * .025); }
      if (kind === 'celebrating') { set('spark', arc); set('y', -arc * 1.5, 'px'); }
      if (kind === 'waving') set('hand', Math.sin(p * Math.PI * 6) * 13, 'deg');
      if (kind === 'look') set('look', wave * 2.5, 'px');
      if (loop || elapsed < duration) this.frame = setTimeout(tick, interval);
      else { this.frame = undefined; done(); }
    };
    this.frame = setTimeout(tick, interval);
  }
  close() { this.stop(); }
}
