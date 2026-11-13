import './style.css';
import { character } from '../src/icons.ts';
import { database } from './signing.mjs';
import { request, readStream } from './transport.mjs';
import { setupPairing, delay } from './pairing.mjs';
import { setupVoice } from './voice.mjs';
const $ = selector => document.querySelector(selector);
const text = (selector, value) => { $(selector).textContent = value; };
$('#mochi').append(character());
let identity, lastStatus, online = false, challenge, sending = false, eventController, scheduleData, day = 'today';
const notice = value => text('#notice', value);
function connectivity(reachable) {
  online = reachable;
  $('#signal').classList.toggle('online', reachable);
  $('#connection').classList.toggle('stale', !reachable);
  const age = lastStatus ? Math.max(0, Math.floor((Date.now() - lastStatus.savedAt) / 60000)) : null;
  text('#connection', reachable ? 'Laptop reachable · private connection' : `Laptop unreachable${age !== null ? ` · last known status ${age < 1 ? 'less than 1 min' : age + ' min'} ago` : ''}`);
  document.querySelectorAll('[data-command], [data-scene], #send, #talk, #revoke').forEach(button => { button.disabled = !reachable || (sending && ['send', 'talk'].includes(button.id)); });
  if (!window.SpeechRecognition && !window.webkitSpeechRecognition) $('#talk').disabled = true;
}
function remaining(focus) {
  const seconds = focus?.remaining_s;
  return Number.isFinite(seconds) ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}` : '—';
}
function renderStatus(state) {
  text('#battery', state.battery ? `${Math.round(state.battery.percent)}% ${state.battery.plugged ? '· charging' : '· battery'}` : 'Battery unavailable');
  text('#greeting', state.scene?.active ? `${state.scene.active} mode.` : 'Ready when you are.');
  text('#app-scene', `${state.current_app || 'App unavailable'} · ${state.scene?.active || 'No active scene'}`);
  text('#next-class', state.next_class ? `${state.next_class.subject} · ${state.next_class.start}` : state.errors?.next_class ? 'Schedule unavailable' : 'Your next moment is yours.');
  text('#faculty', state.next_class ? [state.next_class.faculty, state.next_class.date, state.next_class.room].filter(Boolean).join(' · ') : '');
  text('#due', Array.isArray(state.due_today) ? state.due_today.length : '—');
  text('#focus', remaining(state.focus));
  text('#mood', state.mood?.mood || '—');
  $('.surface').dataset.mood = state.mood?.mood || 'happy';
}
async function refresh() {
  if (!identity?.paired || document.hidden) return;
  try {
    const state = await request(identity, 'GET', 'status');
    lastStatus = { state, savedAt: Date.now() };
    await database('put', 'last-status', lastStatus);
    renderStatus(state); connectivity(true);
  } catch { connectivity(false); }
}
function item(title, details) {
  const row = document.createElement('div'); row.className = 'item';
  const strong = document.createElement('strong'), p = document.createElement('p');
  strong.textContent = title; p.textContent = details; row.append(strong, p); return row;
}
function showSchedule() {
  const list = $('#schedule-list'); list.replaceChildren();
  const rows = scheduleData?.[day] || [];
  if (!rows.length) { list.append(item('Nothing scheduled', 'Room to breathe.')); return; }
  for (const row of rows) list.append(item(row.what || row.subject || 'Class', [row.start && `${row.start}–${row.end}`, row.faculty, row.room, row.due, row.done && 'Completed'].filter(Boolean).join(' · ')));
}
async function showScreen(name) {
  document.querySelectorAll('.screen').forEach(section => { section.hidden = section.id !== name; });
  document.querySelectorAll('[data-screen]').forEach(button => button.setAttribute('aria-current', button.dataset.screen === name ? 'page' : 'false'));
  try {
    if (name === 'schedule') { text('#schedule-list', 'Loading schedule…'); scheduleData = await request(identity, 'GET', 'schedule'); showSchedule(); }
    if (name === 'activity') {
      text('#activity-list', 'Loading activity…');
      const result = await request(identity, 'GET', 'activity'); $('#activity-list').replaceChildren();
      for (const row of result.entries.slice(-20).reverse()) $('#activity-list').append(item(row.command.replaceAll('_', ' '), `${new Date(row.time * 1000).toLocaleString()} · ${row.risk} · ${row.result}`));
    }
    if (name === 'devices') text('#device-name', (await request(identity, 'GET', 'device')).name);
  } catch (error) { notice(error.message); }
}
async function runCommand(command, args = {}) {
  if (!online) return notice('Laptop unreachable. Commands are not queued.');
  notice('Sending…');
  try {
    const result = await request(identity, 'POST', 'commands', { command, args });
    if (result.result === 'approval_required') {
      challenge = { ...result, createdAt: Date.now() }; $('#approval-pin').value = '';
      text('#confirm-description', `${result.command.replaceAll('_', ' ')}${Object.keys(result.args || {}).length ? ' · ' + JSON.stringify(result.args) : ''}`);
      text('#confirm-error', ''); $('#confirm').showModal();
    } else notice(result.data?.text || (result.result === 'completed' ? 'Done.' : 'This action needs local review.'));
    await refresh();
  } catch (error) { notice(error.message); }
}
$('#confirm-form').onsubmit = async event => {
  event.preventDefault(); const button = $('#confirm-form button[type=submit]'); button.disabled = true;
  try {
    if (!challenge || Date.now() - challenge.createdAt >= 60000) throw Error('Challenge expired. Close this screen and request the action again.');
    const current = challenge; challenge = null;
    const result = await request(identity, 'POST', 'approve', { challenge: current.challenge, approval: { pin: $('#approval-pin').value } });
    $('#confirm').close(); notice(result.result === 'completed' ? 'Approved and completed.' : 'The command could not be completed.');
  } catch { text('#confirm-error', 'Approval refused, expired, or PIN locked. Request a new challenge to retry. After three wrong PINs, wait 10 minutes.'); }
  finally { $('#approval-pin').value = ''; button.disabled = false; }
};
$('#cancel-confirm').onclick = () => $('#confirm').close();
$('#confirm').addEventListener('close', () => { challenge = null; $('#approval-pin').value = ''; });
function bubble(content, who) { const div = document.createElement('div'); div.className = 'bubble ' + who; div.textContent = content; $('#messages').append(div); div.scrollIntoView({ block: 'nearest' }); }
async function sendChat(content) {
  if (sending) return;
  if (!online) return notice('Laptop unreachable. Messages are not queued.');
  if (!content.trim() || content.length > 4000) return;
  sending = true; connectivity(online); bubble(content, 'user'); $('#message').value = ''; notice('FRIDAY is thinking…');
  const controller = new AbortController(); let completed = false;
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await request(identity, 'POST', 'chat', { command: 'ask', args: { text: content } }, { stream: true, signal: controller.signal });
    await readStream(response, (topic, payload) => {
      if (topic === 'reply') { bubble(payload.text, 'friday'); if ($('#speak').checked && window.speechSynthesis) speechSynthesis.speak(new SpeechSynthesisUtterance(payload.text)); }
      if (topic === 'done') completed = true;
      if (topic === 'refused') throw Error('FRIDAY could not answer. Please try again.');
    });
    if (!completed) throw Error('Reply interrupted. Nothing was queued; you can retry.');
    notice('');
  } catch (error) { notice(error.message); }
  finally { clearTimeout(timeout); sending = false; connectivity(online); }
}
$('#chat-form').onsubmit = event => { event.preventDefault(); sendChat($('#message').value); };
setupVoice(sendChat);
document.querySelectorAll('[data-screen]').forEach(button => { button.onclick = () => showScreen(button.dataset.screen); });
document.querySelectorAll('[data-command]').forEach(button => { button.onclick = () => runCommand(button.dataset.command); });
document.querySelectorAll('[data-scene]').forEach(button => { button.onclick = () => runCommand('set_scene', { name: button.dataset.scene }); });
document.querySelectorAll('[data-day]').forEach(button => { button.onclick = () => { day = button.dataset.day; document.querySelectorAll('[data-day]').forEach(b => b.setAttribute('aria-pressed', String(b === button))); showSchedule(); }; });
$('#revoke').onclick = async () => {
  if (!window.confirm('Revoke this phone? You will need a new laptop pairing to reconnect.')) return;
  try {
    const result = await request(identity, 'POST', 'commands', { command: 'revoke_self', args: {} });
    if (!result.data?.revoked) throw Error('Revocation was not confirmed.');
  } catch { notice('Revocation was not confirmed. Retry, or revoke this phone on the laptop.'); return; }
  eventController?.abort(); identity = null;
  await database('delete', 'identity'); await database('delete', 'last-status'); location.reload();
};
async function watchEvents() {
  eventController?.abort();
  const controller = new AbortController(); eventController = controller;
  let backoff = 2000;
  while (identity?.paired && !controller.signal.aborted && !document.hidden) {
    try {
      const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(35000)]);
      const response = await request(identity, 'GET', 'events', undefined, { stream: true, signal });
      if (!online) await refresh();
      await readStream(response, (topic, payload) => {
        if (topic === 'focus.tick') text('#focus', remaining(payload));
        if (topic === 'mood.changed') { text('#mood', payload.mood || '—'); $('.surface').dataset.mood = payload.mood || 'happy'; }
        if (topic.startsWith('schedule.')) notice('Your college schedule has an update.');
        if (topic === 'friday.notice') notice(payload.text || payload.title || 'A notice from FRIDAY');
      });
      backoff = 2000;
    } catch { if (!controller.signal.aborted) connectivity(false); backoff = Math.min(backoff * 2, 30000); }
    if (!controller.signal.aborted) await delay(backoff);
  }
}
async function activate(value) {
  identity = value; $('#pairing').hidden = true; $('#panel').hidden = false;
  lastStatus = await database('get', 'last-status');
  if (lastStatus) renderStatus(lastStatus.state);
  connectivity(false); await refresh(); watchEvents();
}
const resumePairing = setupPairing(activate);
window.addEventListener('offline', () => { eventController?.abort(); connectivity(false); });
window.addEventListener('online', () => { refresh(); if (identity?.paired) watchEvents(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) eventController?.abort(); else if (identity?.paired) { refresh(); watchEvents(); } });
setInterval(() => { if (!online) connectivity(false); }, 15000);
setInterval(refresh, 45000);
(async () => {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js', { scope: './' }).catch(() => notice('Offline shell could not be installed. Keep this page open and retry online.'));
  try {
    identity = await database('get', 'identity');
    if (identity?.paired) await activate(identity);
    else { $('#pairing').hidden = false; text('#connection', 'Pair with your laptop over Tailscale'); if (identity) await resumePairing(identity); }
  } catch (error) { $('#pairing').hidden = false; notice('Local key storage or pairing unavailable: ' + error.message); }
})();
