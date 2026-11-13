import { database, generateIdentity } from './signing.mjs';
import { request } from './transport.mjs';
const $ = selector => document.querySelector(selector);
export const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let camera, scanning = false;
export function stopCamera() {
  scanning = false;
  camera?.getTracks().forEach(track => track.stop()); camera = null;
  $('#camera').hidden = true; $('#stop-scan').hidden = true;
}
export function setupPairing(onPaired) {
  const message = text => { $('#pair-message').textContent = text; };
  async function waitForLaptop(identity) {
    $('#pair-form').hidden = true; $('#reset-pair').hidden = false;
    message('Approve this phone on your laptop. Waiting for its signed confirmation…');
    for (let attempt = 0; attempt < 28; attempt++) {
      await delay(4000);
      const response = await request(identity, 'GET', 'pair/status');
      if (response.state === 'paired') {
        identity.paired = true;
        await database('put', 'identity', identity);
        $('#reset-pair').hidden = true;
        await onPaired(identity); return;
      }
    }
    throw Error('Pairing expired. Ask the laptop for a new QR.');
  }
  $('#reset-pair').onclick = async () => {
    await database('delete', 'identity');
    location.reload();
  };
  $('#pair-form').onsubmit = async event => {
    event.preventDefault(); stopCamera();
    const submit = $('#pair-form button[type=submit]'); submit.disabled = true;
    try {
      const payload = JSON.parse($('#pair-code').value.trim());
      if (payload.url !== location.origin || payload.signing_prefix !== '/remote' ||
          !/^sha256:[a-f0-9]{64}$/.test(payload.fingerprint) || typeof payload.token !== 'string' ||
          !Number.isFinite(payload.expires) || payload.expires * 1000 <= Date.now()) throw Error('Use a fresh QR from this laptop, on its HTTPS Tailscale address.');
      const pin = $('#new-pin').value;
      if (!/^[0-9]{6}$/.test(pin)) throw Error('Enter a 6-digit PIN.');
      const identity = await generateIdentity($('#phone-name').value.trim());
      identity.fingerprint = payload.fingerprint;
      await database('put', 'identity', identity);
      await request(identity, 'POST', 'pair', { token: payload.token, public_key: identity.pem, name: identity.name, pin });
      $('#new-pin').value = ''; $('#pair-code').value = '';
      await waitForLaptop(identity);
    } catch (error) { message(error.message); }
    finally { submit.disabled = false; $('#new-pin').value = ''; }
  };
  $('#scan').onclick = async () => {
    stopCamera();
    if (!('BarcodeDetector' in window) || !navigator.mediaDevices?.getUserMedia) {
      message('QR scanning is unavailable in this browser. Paste the pairing code instead.'); return;
    }
    try {
      const detector = new window.BarcodeDetector({ formats: ['qr_code'] });
      camera = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
      const video = $('#camera'); video.srcObject = camera; video.hidden = false; $('#stop-scan').hidden = false;
      await video.play(); scanning = true;
      while (scanning) {
        const results = await detector.detect(video);
        if (results.length) { $('#pair-code').value = results[0].rawValue; stopCamera(); message('QR read. Set your PIN, then pair.'); }
        else await delay(200);
      }
    } catch { stopCamera(); message('Camera unavailable. Paste the pairing code instead.'); }
  };
  $('#stop-scan').onclick = stopCamera;
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopCamera(); });
  return waitForLaptop;
}
