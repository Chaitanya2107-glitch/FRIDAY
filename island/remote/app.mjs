import './style.css';
import { character } from '../src/icons.ts';
import { database } from './signing.mjs';
import { request, readStream } from './transport.mjs';
import { setupPairing, delay } from './pairing.mjs';
import { setupVoice } from './voice.mjs';
import { CommandQueue, indexedQueue, queueable } from './queue.mjs';
import { presenceText } from '../src/presence.ts';
const $ = selector => document.querySelector(selector);
const text = (selector, value) => { $(selector).textContent = value; };
$('#mochi').append(character());
let identity, lastStatus, online = false, challenge, sending = false, eventController, scheduleData, day = 'today';
let currentPresence;
let wellbeing, checkinSending = false;
let privateQuestion, privateCheckSending = false, privateCheckEpoch = 0;
let goalSending = false, goalEpoch = 0;
const pendingGoalLogs = new Map();
const notice = value => text('#notice', value);
const queueStore = indexedQueue();
const queue = new CommandQueue(queueStore, async envelope => {
  try {
    const result = await request(identity, 'POST', 'queue', envelope);
    const report = envelope.command === 'ring_laptop' && result.result === 'completed'
      ? `${result.data?.text || 'Ring requested.'} Last active app: ${result.data?.app || 'unknown'} · idle ${result.data?.idle_seconds ?? 'unknown'} seconds.`
      : result.data?.text || 'Done.';
    notice(result.result === 'completed' ? report : 'Outcome uncertain or refused. Check laptop activity; this action will not retry.');
    return result;
  } catch (error) {
    if (error.networkUnavailable) connectivity(false);
    notice(error.message); throw error;
  }
}, { changed: renderQueue });
async function renderQueue() {
  const rows = await queue.rows(), list = $('#waiting-list');
  $('#waiting').hidden = !rows.length; list.replaceChildren();
  const waiting = rows.filter(row => row.state === 'waiting').length;
  text('#waiting-title', waiting ? `${waiting} action${waiting === 1 ? '' : 's'} waiting` : 'Saved action status');
  for (const row of rows) {
    const minutes = Math.max(1, Math.ceil((row.expires_at * 1000 - Date.now()) / 60000));
    const state = queue.activeId === row.id ? 'Sending now' : row.state === 'waiting' ? `Waiting · expires in ${minutes} min` : ({ expired: 'Expired · will not send again', refused: 'Refused · will not retry', uncertain: 'Outcome uncertain · will not retry' }[row.state] || row.state);
    const entry = item(row.command.replaceAll('_', ' '), state);
    const cancel = document.createElement('button');
    cancel.textContent = row.state === 'waiting' ? 'Cancel waiting action' : 'Dismiss';
    cancel.disabled = queue.activeId === row.id;
    cancel.onclick = async () => { await queueStore.remove(row.id); await renderQueue(); };
    entry.append(cancel); list.append(entry);
  }
}
function drainQueue() {
  if (!identity?.paired || !online || document.hidden) return;
  const drain = () => queue.drain().catch(() => notice('Waiting actions could not be read. Check phone storage.'));
  // Other tabs share the queue; stable server IDs additionally protect lost replies.
  if (navigator.locks) navigator.locks.request('friday-command-queue', { ifAvailable: true }, lock => lock ? drain() : undefined);
  else drain();
}
function connectivity(reachable) {
  online = reachable;
  if (!reachable) { clearPrivateCheck(); clearGoals(); }
  renderPresence();
  renderWellbeing();
  renderGoalControls();
  $('#signal').classList.toggle('online', reachable);
  $('#connection').classList.toggle('stale', !reachable);
  const age = lastStatus ? Math.max(0, Math.floor((Date.now() - lastStatus.savedAt) / 60000)) : null;
  text('#connection', reachable ? 'Laptop reachable · private connection' : `Laptop unreachable${age !== null ? ` · last known status ${age < 1 ? 'less than 1 min' : age + ' min'} ago` : ''}`);
  document.querySelectorAll('[data-command], [data-scene], #send, #talk, #revoke').forEach(button => {
    const safe = queueable(button.dataset.command || (button.dataset.scene && 'set_scene'));
    button.disabled = (!reachable && !safe) || (sending && ['send', 'talk'].includes(button.id));
  });
  if (!window.SpeechRecognition && !window.webkitSpeechRecognition) $('#talk').disabled = true;
}
function remaining(focus) {
  const seconds = focus?.remaining_s;
  return Number.isFinite(seconds) ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}` : '—';
}
function renderStatus(state) {
  currentPresence = state.presence;
  renderPresence();
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
function renderPresence() {
  const view = presenceText(currentPresence, !online);
  text('#presence-state', view.label);
  text('#presence-confidence', view.confidence);
  text('#presence-reason', view.detail);
  $('#presence').classList.toggle('stale', !online && view.available);
}
function renderWellbeing() {
  const confirmed = wellbeing?.confirmed === true;
  $('#wellbeing-options').hidden = !confirmed;
  $('#wellbeing-setup').hidden = confirmed;
  document.querySelectorAll('[data-wellbeing-score]').forEach(button => {
    button.disabled = !online || !confirmed || wellbeing?.can_log !== true || checkinSending;
  });
  $('#view-private-check').disabled = !online || privateCheckSending;
  document.querySelectorAll('[data-care-choice]').forEach(button => {
    button.disabled = !online || !privateQuestion || privateCheckSending;
  });
  text('#wellbeing-status', !online ? 'Laptop unreachable. Check-ins are sent live and never queued.'
    : wellbeing === undefined ? 'Check-in unavailable. Open private care setup on your laptop or try again online.'
    : !confirmed ? 'Off until you choose and confirm it.'
    : wellbeing.logged_today ? 'Today’s check-in is saved on your laptop.'
    : wellbeing.can_log ? 'Optional. Choose a number on your own scale.'
    : 'Your chosen check-in window is closed, or care is paused.');
}
async function refreshWellbeing() {
  if (!identity?.paired || !online) return;
  try {
    const response = await request(identity, 'POST', 'commands', { command: 'care_status', args: {} });
    const value = response.data?.wellbeing;
    if (response.result !== 'completed' || !value) throw Error('Care unavailable');
    wellbeing = Object.fromEntries(['confirmed', 'can_log', 'logged_today'].map(key => [key, value[key] === true]));
  } catch { wellbeing = undefined; }
  renderWellbeing();
}
async function logWellbeing(score) {
  if (!online || checkinSending || wellbeing?.can_log !== true) return;
  checkinSending = true; renderWellbeing();
  try {
    const result = await request(identity, 'POST', 'commands', { command: 'care_checkin', args: { score } });
    if (result.result !== 'completed' || result.data?.recorded !== true) throw Error('Check-in refused');
    if (wellbeing) wellbeing.logged_today = true;
    text('#wellbeing-status', 'Today’s check-in is saved on your laptop.');
  } catch (error) {
    if (error.networkUnavailable) connectivity(false);
    notice('Check-in was not confirmed. Nothing was queued; check your chosen window and try again online.');
  } finally { checkinSending = false; await refreshWellbeing(); renderWellbeing(); }
}
function clearPrivateCheck() {
  privateCheckEpoch++; privateQuestion = undefined; privateCheckSending = false;
  $('#private-check-details').hidden = true; text('#private-check-text', ''); text('#private-check-status', '');
}
async function viewPrivateCheck() {
  if (!online || privateCheckSending) return;
  clearPrivateCheck();
  const epoch = privateCheckEpoch;
  privateCheckSending = true; renderWellbeing();
  try {
    const result = await request(identity, 'POST', 'commands', { command: 'care_question', args: {} });
    if (epoch !== privateCheckEpoch || !online || document.hidden) return;
    const value = result.data;
    if (result.result !== 'completed' || !value) throw Error('Private check unavailable');
    if (value.pending !== true) { text('#private-check-status', 'No private check is pending in your chosen window.'); return; }
    privateQuestion = { id: value.id };
    text('#private-check-text', value.text); $('#private-check-details').hidden = false;
  } catch {
    if (epoch === privateCheckEpoch) text('#private-check-status', 'Private check unavailable. Try again while connected.');
  } finally {
    if (epoch === privateCheckEpoch) { privateCheckSending = false; renderWellbeing(); }
  }
}
async function answerPrivateCheck(choice) {
  if (!online || !privateQuestion || privateCheckSending) return;
  const id = privateQuestion.id, epoch = privateCheckEpoch;
  privateCheckSending = true; renderWellbeing();
  try {
    const result = await request(identity, 'POST', 'commands', { command: 'care_answer', args: { id, choice } });
    if (epoch !== privateCheckEpoch) return;
    if (result.result !== 'completed' || result.data?.recorded !== true) throw Error('Answer refused');
    clearPrivateCheck(); text('#private-check-status', 'Your choice is saved locally.');
  } catch {
    if (epoch === privateCheckEpoch) { clearPrivateCheck(); text('#private-check-status', 'Answer was not confirmed. Nothing was queued; reopen the private check to try again.'); }
  } finally {
    if (epoch === privateCheckEpoch) privateCheckSending = false;
    renderWellbeing();
  }
}
function renderGoalControls() {
  $('#view-goals').disabled = !online || goalSending;
  document.querySelectorAll('#goals-list button').forEach(button => { button.disabled = !online || goalSending; });
}
function clearGoals() {
  goalEpoch++;
  $('#goals-list').replaceChildren(); text('#goals-status', ''); renderGoalControls();
}
async function viewGoals() {
  if (!online || goalSending) return;
  clearGoals();
  const epoch = goalEpoch;
  goalSending = true; renderGoalControls();
  try {
    const result = await request(identity, 'POST', 'commands', { command: 'goal_status', args: {} });
    if (epoch !== goalEpoch || !online || document.hidden) return;
    if (result.result !== 'completed' || !Array.isArray(result.data?.goals)) throw Error('Goals unavailable');
    for (const goal of result.data.goals) {
      const row = item(goal.title, goal.done === null ? `Progress unavailable. Target: ${goal.target} ${goal.unit}` : `${goal.done} / ${goal.target} ${goal.unit}`);
      if (goal.manual === true) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = `${pendingGoalLogs.has(goal.id) ? 'Retry previous ' : ''}+1 ${goal.unit}`;
        button.setAttribute('aria-label', `${pendingGoalLogs.has(goal.id) ? 'Retry previous log of' : 'Log'} 1 ${goal.unit} for ${goal.title}`);
        button.onclick = () => logGoal(goal.id);
        row.append(button);
      }
      $('#goals-list').append(row);
    }
    if (pendingGoalLogs.size) text('#goals-status', 'An earlier log was not confirmed. Retry confirms the same log without adding another unit.');
    else if (!result.data.goals.length) text('#goals-status', 'No confirmed goals. Set one up in private chat on your laptop.');
  } catch {
    if (epoch === goalEpoch) text('#goals-status', 'Goals unavailable. Try again while connected.');
  } finally { goalSending = false; renderGoalControls(); }
}
async function logGoal(id) {
  if (!online || goalSending) return;
  const epoch = goalEpoch, args = pendingGoalLogs.get(id) || { id, value: 1, receipt: crypto.randomUUID().replaceAll('-', '') };
  pendingGoalLogs.set(id, args);
  goalSending = true; text('#goals-status', 'Saving…'); renderGoalControls();
  try {
    const result = await request(identity, 'POST', 'commands', { command: 'goal_log', args });
    if (result.result !== 'completed' || result.data?.recorded !== true) throw Error('Goal log refused');
    pendingGoalLogs.delete(id);
    if (epoch !== goalEpoch || !online || document.hidden) return;
    clearGoals(); text('#goals-status', 'Saved on your laptop. Tap View goals to refresh progress.');
  } catch (error) {
    if (epoch !== goalEpoch) return;
    if (error.networkUnavailable) connectivity(false);
    else clearGoals();
    text('#goals-status', 'Log was not confirmed. Reconnect and tap View goals to check progress and retry the same log.');
  } finally { goalSending = false; renderGoalControls(); }
}
async function refresh() {
  if (!identity?.paired || document.hidden) return;
  try {
    const state = await request(identity, 'GET', 'status');
    lastStatus = { state, savedAt: Date.now() };
    await database('put', 'last-status', lastStatus);
    renderStatus(state); connectivity(true); drainQueue(); await refreshWellbeing();
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
  clearGoals();
  if (name !== 'home') clearPrivateCheck();
  document.querySelectorAll('.screen').forEach(section => { section.hidden = section.id !== name; });
  document.querySelectorAll('[data-screen]').forEach(button => button.setAttribute('aria-current', button.dataset.screen === name ? 'page' : 'false'));
  try {
    if (name === 'home') await refreshWellbeing();
    if (name === 'timeline') {
      text('#timeline-list', 'Loading recorded timeline…');
      const result = await request(identity, 'GET', 'timeline');
      $('#timeline-list').replaceChildren();
      for (const device of ['laptop', 'phone']) {
        const lane = document.createElement('section');
        lane.append(item(device === 'laptop' ? 'Laptop' : 'Phone', 'Today · recorded activity'));
        const rows = result.segments.filter(row => row.device === device);
        if (!rows.length) lane.append(item('No observations', 'Missing data does not mean no use.'));
        for (const row of rows) lane.append(item(row.label || row.app, `${new Date(row.start*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}–${new Date(row.end*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})} · ${row.category}`));
        $('#timeline-list').append(lane);
      }
    }
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
  if (queueable(command)) {
    try {
      await queue.enqueue(command, args, Number($('#queue-expiry').value));
      notice(online ? 'Sending…' : 'Waiting for your laptop. You can cancel below.');
      drainQueue();
    } catch (error) { notice(error.message); }
    return;
  }
  if (!online) return notice('Laptop unreachable. Commands needing confirmation cannot wait in the queue.');
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
      if (topic === 'reply') { bubble(payload.text, 'friday'); if (payload.allow_speech !== false && $('#speak').checked && window.speechSynthesis) speechSynthesis.speak(new SpeechSynthesisUtterance(payload.text)); }
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
$('#view-private-check').onclick = viewPrivateCheck;
$('#view-goals').onclick = viewGoals;
document.querySelectorAll('[data-care-choice]').forEach(button => {
  button.onclick = () => answerPrivateCheck(button.dataset.careChoice);
});
document.querySelectorAll('[data-wellbeing-score]').forEach(button => {
  button.onclick = () => logWellbeing(Number(button.dataset.wellbeingScore));
});
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
  eventController?.abort(); identity = null; pendingGoalLogs.clear(); clearGoals();
  await queueStore.clear(); await database('delete', 'identity'); await database('delete', 'last-status'); location.reload();
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
        if (topic === 'presence.changed') {
          currentPresence = payload; renderPresence();
          if (presenceText(payload).available && lastStatus) {
            lastStatus.state.presence = payload;
            void database('put', 'last-status', lastStatus).catch(() => {});
          }
        }
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
  if (await database('get', 'queue-device') !== identity.id) await queueStore.clear();
  await database('put', 'queue-device', identity.id);
  lastStatus = await database('get', 'last-status');
  if (lastStatus) renderStatus(lastStatus.state);
  connectivity(false); await renderQueue(); await refresh(); watchEvents();
}
const resumePairing = setupPairing(activate);
window.addEventListener('offline', () => { eventController?.abort(); connectivity(false); });
window.addEventListener('online', () => { refresh(); if (identity?.paired) watchEvents(); });
window.addEventListener('pagehide', clearGoals);
document.addEventListener('visibilitychange', () => { if (document.hidden) { clearPrivateCheck(); clearGoals(); eventController?.abort(); } else if (identity?.paired) { refresh(); watchEvents(); } });
setInterval(() => { if (!online) connectivity(false); if (identity?.paired) { renderQueue().catch(() => {}); drainQueue(); } }, 15000);
setInterval(refresh, 45000);
(async () => {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js', { scope: './' }).catch(() => notice('Offline shell could not be installed. Keep this page open and retry online.'));
  try {
    identity = await database('get', 'identity');
    if (identity?.paired) await activate(identity);
    else { $('#pairing').hidden = false; text('#connection', 'Pair with your laptop over Tailscale'); if (identity) await resumePairing(identity); }
  } catch (error) { $('#pairing').hidden = false; notice('Local key storage or pairing unavailable: ' + error.message); }
})();
