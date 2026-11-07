import './hud.css';
import { call, native, on } from './native';
import { duration, remaining, type HudFrame, type HudStatus } from './hud-model';

const root = document.querySelector<HTMLElement>('#hud')!;
function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = '') {
  const node = document.createElement(tag); node.className = className; node.textContent = text; return node;
}
function text(node: HTMLElement, value: string) { if (node.textContent !== value) node.textContent = value; }
const header = element('header', 'hud-header');
const identity = element('div', 'identity'); identity.append(element('span', 'signal-dot'), element('span', '', 'F R I D A Y'));
const mode = element('span', 'hud-mode', 'PERSONAL SYSTEMS');
const done = element('button', 'hud-done', 'Done'); done.hidden = true;
done.onclick = () => void call('hud_finish');
header.onpointerdown = event => { if (event.button === 0 && editing && event.target !== done) void call('hud_drag'); };
header.append(identity, mode, done);
const clock = element('section', 'hud-clock');
const clockLine = element('div', 'clock-line'); const time = element('time'); const period = element('span', 'clock-period');
clockLine.append(time, period);
const date = element('div', 'hud-date'); const scene = element('span', 'hud-scene', 'STANDBY');
const dateLine = element('div', 'date-line'); dateLine.append(date, scene); clock.append(clockLine, dateLine);
const system = element('section', 'hud-system'); system.setAttribute('aria-label', 'System load');
function gauge(label: string) {
  const node = element('div', 'gauge');
  // Fixed SVG markup only. All backend strings use textContent.
  node.innerHTML = '<svg viewBox="0 0 100 100" aria-hidden="true"><circle class="gauge-ticks" cx="50" cy="50" r="46"/><circle class="gauge-track" cx="50" cy="50" r="39"/><circle class="gauge-value" cx="50" cy="50" r="39" pathLength="100"/></svg>';
  const value = element('span', 'gauge-number', '—'); const name = element('span', 'gauge-label', label);
  node.append(value, name); system.append(node);
  return { node, value, name, ring: node.querySelector<SVGCircleElement>('.gauge-value')! };
}
const gauges = { cpu: gauge('CPU'), ram: gauge('RAM'), battery: gauge('BATTERY'), gpu: gauge('GPU') };
const work = element('section', 'hud-work');
const classCard = element('article', 'class-card glass');
const classLabel = element('div', 'eyebrow', 'UP NEXT'); const subject = element('h2');
const faculty = element('p', 'class-faculty'); const classMeta = element('div', 'class-meta');
const room = element('span'); const starts = element('time'); const countdown = element('span', 'class-countdown');
classMeta.append(room, starts); classCard.append(classLabel, subject, faculty, classMeta, countdown);
const focus = element('article', 'focus-card glass');
const focusGauge = gauge('FOCUS'); focusGauge.node.remove(); focus.append(focusGauge.node, element('span', 'focus-caption', 'ONE THING AT A TIME'));
work.append(classCard, focus);
const network = element('section', 'hud-network glass');
const networkTop = element('div', 'network-top'); networkTop.append(element('span', 'eyebrow', 'NETWORK'));
const rates = element('div', 'network-rates'); const down = element('span'); const up = element('span'); rates.append(down, up);
const spark = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); spark.setAttribute('viewBox', '0 0 400 32'); spark.setAttribute('preserveAspectRatio', 'none');
const download = document.createElementNS(spark.namespaceURI, 'polyline'); const upload = document.createElementNS(spark.namespaceURI, 'polyline');
upload.setAttribute('class', 'upload-line'); spark.append(download, upload); network.append(networkTop, rates, spark);
const activity = element('section', 'hud-activity'); const activityTop = element('div', 'activity-top');
const activityTotal = element('span', 'activity-total'); activityTop.append(element('span', 'eyebrow', 'TODAY / TIME WELL SPENT'), activityTotal);
const strip = element('div', 'activity-strip'); const legend = element('div', 'activity-legend'); activity.append(activityTop, strip, legend);
const footer = element('footer', 'hud-footer'); const status = element('span', '', 'LOCAL / LIVE'); footer.append(status, element('span', '', 'QUIETLY, BY YOUR SIDE'));
root.append(header, clock, system, work, network, activity, footer);
for (const edge of ['nw', 'ne', 'sw', 'se']) {
  const handle = element('button', `resize-handle ${edge}`); handle.setAttribute('aria-label', `Resize ${edge}`);
  handle.onpointerdown = event => { event.preventDefault(); void call('hud_drag', { edge }); }; root.append(handle);
}
let editing = false, lastActivity = '', lastNetworkAt = 0, osReduced = false, appReduced = false;
let history: [number, number][] = [];
const formatter = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hour12: true });
function setGauge(target: ReturnType<typeof gauge>, value: number | null, label?: string) {
  const percent = value === null || !Number.isFinite(value) ? null : Math.max(0, Math.min(100, value));
  text(target.value, label ?? (percent === null ? '—' : `${Math.round(percent)}`));
  target.ring.style.strokeDashoffset = String(100 - (percent ?? 0));
  target.node.setAttribute('aria-label', `${target.name.textContent}: ${label ?? (percent === null ? 'unavailable' : `${Math.round(percent)} percent`)}`);
}
function speed(value: number) { return value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB/s` : `${Math.round(value / 1024)} KB/s`; }
function render(frame: HudFrame) {
  if (!frame?.state?.settings) return;
  const { state, stats, saver } = frame; const settings = state.settings; const now = Date.now() / 1000;
  appReduced = frame.reduced_motion === true; root.classList.toggle('reduced-motion', osReduced || appReduced);
  root.classList.toggle('saver', saver); root.classList.toggle('top-layer', settings.layer === 'top');
  root.style.setProperty('--hud-opacity', String(settings.opacity));
  const widgets = settings.widgets;
  clock.hidden = !widgets.clock && !widgets.scene; clockLine.hidden = !widgets.clock; date.hidden = !widgets.clock;
  system.hidden = !widgets.system; network.hidden = !widgets.network;
  scene.hidden = !widgets.scene; text(scene, state.scene ? state.scene.toUpperCase() : 'STANDBY');
  const dateTime = new Date(); const parts = formatter.formatToParts(dateTime);
  text(time, parts.filter(p => p.type !== 'dayPeriod').map(p => p.value).join('').trim());
  text(period, parts.find(p => p.type === 'dayPeriod')?.value ?? '');
  text(date, dateTime.toLocaleDateString(undefined, { weekday: 'short', day: '2-digit', month: 'long' }).toUpperCase());
  setGauge(gauges.cpu, stats?.cpu_percent ?? null); setGauge(gauges.ram, stats?.ram?.percent ?? null);
  gauges.battery.node.hidden = !stats?.battery; gauges.gpu.node.hidden = !stats?.gpu;
  setGauge(gauges.battery, stats?.battery?.percent ?? null);
  text(gauges.battery.name, stats?.battery?.charging ? 'CHARGING ↯' : 'BATTERY');
  setGauge(gauges.gpu, stats?.gpu?.percent ?? null);
  const next = state.next_class; const until = next ? (Date.parse(next.starts_at) / 1000 - now) : -1;
  classCard.hidden = !widgets.class || !next || until < -60 || !Number.isFinite(until);
  if (next) {
    text(subject, next.subject); text(faculty, next.faculty); text(room, next.room || 'Room TBA');
    const at = new Date(next.starts_at); text(starts, Number.isFinite(at.getTime()) ? at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '');
    text(countdown, until <= 0 ? 'STARTING NOW' : `IN ${duration(until)}`);
    classCard.classList.toggle('soon', until >= 0 && until <= 900);
  }
  const left = remaining(state.focus, now);
  focus.hidden = !widgets.focus || !state.focus || left <= 0;
  if (state.focus) {
    setGauge(focusGauge, left / state.focus.duration_s * 100, `${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, '0')}`);
    text(focusGauge.name, state.focus.ends_at === null ? 'PAUSED' : 'FOCUS');
  }
  work.hidden = classCard.hidden && focus.hidden;
  if (stats?.network && stats.sampled_at !== lastNetworkAt) {
    lastNetworkAt = stats.sampled_at; history.push([stats.network.download_bps, stats.network.upload_bps]); history = history.slice(-40);
    const ceiling = Math.max(1024, ...history.flat());
    for (const [index, line] of [[0, download], [1, upload]] as const)
      line.setAttribute('points', history.map((sample, i) => `${i * 400 / 39},${30 - sample[index] / ceiling * 27}`).join(' '));
  }
  text(down, `↓ ${stats?.network ? speed(stats.network.download_bps) : '—'}`);
  text(up, `↑ ${stats?.network ? speed(stats.network.upload_bps) : '—'}`);
  activity.hidden = !widgets.activity || state.activity === null;
  const activityKey = JSON.stringify(state.activity);
  if (activityKey !== lastActivity) {
    lastActivity = activityKey; strip.replaceChildren(); legend.replaceChildren();
    const entries = Object.entries(state.activity ?? {}).filter(([, seconds]) => Number.isFinite(seconds) && seconds > 0).sort((a, b) => b[1] - a[1]);
    const total = entries.reduce((sum, [, seconds]) => sum + seconds, 0); text(activityTotal, duration(total));
    entries.forEach(([category, seconds], index) => {
      const segment = element('span'); segment.style.flex = String(seconds); segment.style.opacity = String(Math.max(.25, 1 - index * .13));
      segment.title = `${category}: ${duration(seconds)}`; strip.append(segment);
      const item = element('span', '', `${category.toUpperCase()} ${duration(seconds)}`); legend.append(item);
    });
    if (!entries.length) legend.append(element('span', '', 'NO ACTIVITY YET'));
  }
  text(status, frame.error ? 'READINGS UNAVAILABLE' : saver ? 'SAVER / 5 SECOND READINGS' : 'LOCAL / LIVE');
}
await on<HudFrame>('hud-data', render);
await on<HudStatus>('hud-status', value => {
  editing = value.editing; root.classList.toggle('editing', editing); done.hidden = !editing;
  osReduced = value.reduce_motion; root.classList.toggle('reduced-motion', osReduced || appReduced);
  root.classList.toggle('shown', value.visible);
  text(mode, editing ? 'DRAG TO POSITION' : 'PERSONAL SYSTEMS');
});
if (native) await call('hud_ready');
