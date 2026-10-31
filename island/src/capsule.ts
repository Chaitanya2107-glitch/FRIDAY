import { icon } from './icons';
import { call, native } from './native';
import { element as el, readReminder } from './state';
import type { DesktopStatus, MediaSession, Mode, PillSnippet } from './types';

/** Rest's local clock, battery and optional Windows media strip. */
export class Capsule {
  readonly left = el('div', 'rest-info rest-clock');
  readonly right = el('div', 'rest-info rest-detail');
  readonly media = el('div', 'capsule-media');
  private time = el('time', 'clock-time');
  private period = el('span', 'clock-period');
  private weekday = el('span', 'clock-secondary');
  private date = el('time', 'clock-date');
  private reminder = el('span', 'capsule-reminder');
  private reminderData: PillSnippet | null = null;
  private reminderTimer?: ReturnType<typeof setTimeout>;
  private battery = el('span', 'capsule-battery clock-secondary');
  private charge = el('span', 'battery-charge');
  private percent = el('span');
  private title = el('span', 'media-title');
  private artist = el('span', 'media-artist');
  private previous = this.control('Previous track', 'previous', 'previous');
  private toggle = this.control('Play', 'play', 'toggle');
  private next = this.control('Next track', 'next', 'next');
  private current: MediaSession | null = null;
  private visible = false;
  private mode: Mode = 'rest';
  private reading = false;
  private controlling = false;
  private clockTimer?: ReturnType<typeof setTimeout>;
  private statusTimer?: ReturnType<typeof setTimeout>;
  private lastStatus = '';
  private clockFormat = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  private dateFormat = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' });
  private dayFormat = new Intl.DateTimeFormat('en-US', { weekday: 'long' });

  constructor(private message: (text: string, bad?: boolean) => void) {
    const clock = el('div', 'clock-primary'); clock.append(this.time, this.period);
    this.left.append(clock, this.weekday);
    const batteryIcon = el('span', 'battery-icon'); batteryIcon.append(icon('battery'), this.charge);
    this.battery.append(batteryIcon, this.percent);
    this.battery.hidden = true;
    this.reminder.hidden = true; this.reminder.setAttribute('aria-live', 'polite');
    this.right.append(this.date, this.reminder, this.battery);
    const metadata = el('div', 'media-metadata'); metadata.append(this.title, this.artist);
    const controls = el('div', 'media-controls'); controls.append(this.previous, this.toggle, this.next);
    this.media.append(icon('music'), metadata, controls);
    this.media.setAttribute('aria-label', 'Current media');
    this.media.hidden = true;
    document.addEventListener('visibilitychange', () => this.setMode(this.mode));
    window.addEventListener('focus', () => { if (this.visible) { this.tickClock(); void this.refresh(); } });
    this.tickClock();
  }

  setMode(mode: Mode) {
    this.mode = mode;
    this.visible = mode !== 'hidden' && mode !== 'sneak' && !document.hidden;
    clearTimeout(this.clockTimer); clearTimeout(this.statusTimer);
    if (this.visible) { this.tickClock(); void this.refresh(); }
  }

  setReminder(value: unknown) {
    this.reminderData = readReminder(value);
    this.updateReminder();
  }

  private updateReminder() {
    clearTimeout(this.reminderTimer);
    this.reminderData = readReminder(this.reminderData);
    this.date.hidden = !!this.reminderData;
    this.reminder.hidden = !this.reminderData;
    const text = this.reminderData?.text ?? '';
    if (this.reminder.textContent !== text) this.reminder.textContent = text;
    this.reminder.title = text;
    if (this.reminderData) this.reminderTimer = setTimeout(() => this.updateReminder(), this.reminderData.expires_at - Date.now() + 1);
  }

  private tickClock() {
    clearTimeout(this.clockTimer);
    const now = new Date();
    const parts = this.clockFormat.formatToParts(now);
    this.time.textContent = parts.filter(p => p.type !== 'dayPeriod').map(p => p.value).join('').trim();
    this.period.textContent = parts.find(p => p.type === 'dayPeriod')?.value ?? '';
    this.time.dateTime = now.toISOString(); this.time.setAttribute('aria-label', this.clockFormat.format(now));
    this.weekday.textContent = this.dayFormat.format(now);
    this.date.textContent = this.dateFormat.format(now); this.date.dateTime = now.toISOString();
    this.date.title = now.toLocaleDateString(undefined, { dateStyle: 'full' });
    this.updateReminder();
    // Minute-boundary refresh; no ticking seconds or continuous render loop.
    if (this.visible) this.clockTimer = setTimeout(() => this.tickClock(), 60000 - Date.now() % 60000 + 25);
  }

  private async refresh() {
    if (!native || !this.visible || this.reading) return;
    this.reading = true;
    clearTimeout(this.statusTimer);
    try { this.render(await call<DesktopStatus>('desktop_status')); }
    catch { this.render({ battery: null, media: null }); }
    finally {
      this.reading = false;
      if (this.visible) this.statusTimer = setTimeout(() => void this.refresh(), 2000);
    }
  }

  private render(status: DesktopStatus) {
    const serialized = JSON.stringify(status);
    if (this.lastStatus === serialized) return;
    this.lastStatus = serialized;
    const battery = status.battery;
    this.battery.hidden = !battery;
    if (battery) {
      this.percent.textContent = battery.percent === null ? '—' : `${battery.percent}%`;
      this.battery.classList.toggle('charging', battery.charging);
      this.battery.classList.toggle('low', battery.percent !== null && battery.percent <= 20 && !battery.plugged_in);
      this.battery.title = `${battery.percent === null ? 'Battery status unavailable' : `Battery ${battery.percent}%`}${battery.charging ? ' · Charging' : battery.plugged_in ? ' · Plugged in' : ''}`;
      this.battery.setAttribute('aria-label', this.battery.title);
      this.charge.style.setProperty('--charge', `${battery.percent ?? 0}%`);
    }
    this.current = status.media;
    this.media.hidden = !this.current;
    if (!this.current) return;
    this.title.textContent = this.current.title || 'Untitled media';
    this.artist.textContent = this.current.artist || (this.current.playing ? 'Playing' : 'Paused');
    this.media.classList.toggle('paused', !this.current.playing);
    this.media.title = `${this.current.playing ? 'Playing' : 'Paused'} · ${this.title.textContent}${this.current.artist ? ` — ${this.current.artist}` : ''}`;
    const label = this.current.playing ? 'Pause' : 'Play';
    this.toggle.title = label; this.toggle.setAttribute('aria-label', label);
    this.toggle.replaceChildren(icon(this.current.playing ? 'pause' : 'play'));
    this.updateControls();
  }

  private updateControls() {
    this.previous.disabled = this.controlling || !this.current?.can_previous;
    this.toggle.disabled = this.controlling || !this.current?.can_toggle;
    this.next.disabled = this.controlling || !this.current?.can_next;
  }

  private control(label: string, glyph: string, action: 'previous' | 'toggle' | 'next') {
    const node = el('button', 'media-button'); node.title = label; node.setAttribute('aria-label', label);
    node.append(icon(glyph));
    // Media clicks preserve the keyboard focus in the owner's application.
    node.onpointerdown = event => event.preventDefault();
    node.onclick = async () => {
      if (!this.current || this.controlling) return;
      this.controlling = true; this.updateControls();
      try { await call('media_control', { action, source: this.current.source }); }
      catch (error) { this.message(String(error), true); }
      finally { this.controlling = false; this.updateControls(); void this.refresh(); }
    };
    return node;
  }
}
