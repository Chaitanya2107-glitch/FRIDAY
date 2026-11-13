export function setupVoice(send) {
  const button = document.querySelector('#talk'), info = document.querySelector('#voice-info');
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) { button.disabled = true; info.textContent = 'Voice input is not supported in this browser. You can still type to FRIDAY.'; return; }
  info.textContent = 'Hold to speak, release to send. Your browser handles speech recognition; it may use its own online service.';
  const recognition = new Recognition(); recognition.lang = navigator.language; recognition.interimResults = false;
  let active = false;
  recognition.onresult = event => {
    const text = event.results[0]?.[0]?.transcript;
    if (text) { document.querySelector('#message').value = text; send(text).catch(error => { info.textContent = error.message; }); }
  };
  recognition.onerror = () => { info.textContent = 'Speech recognition unavailable or microphone denied. Please type your message.'; };
  recognition.onend = () => { active = false; button.classList.remove('recording'); };
  const start = () => { if (active || button.disabled) return; try { recognition.start(); active = true; button.classList.add('recording'); } catch { /* An existing recognition session is ending. */ } };
  const stop = () => { if (active) recognition.stop(); button.classList.remove('recording'); };
  button.onpointerdown = event => { button.setPointerCapture(event.pointerId); start(); };
  button.onpointerup = stop; button.onpointercancel = () => recognition.abort();
  button.onkeydown = event => { if (event.code === 'Space' || event.code === 'Enter') { event.preventDefault(); start(); } };
  button.onkeyup = event => { if (event.code === 'Space' || event.code === 'Enter') stop(); };
  document.addEventListener('visibilitychange', () => { if (document.hidden) recognition.abort(); });
}
