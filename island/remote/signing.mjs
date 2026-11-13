const encoder = new TextEncoder();
export const bytes = text => encoder.encode(text);
export const hex = buffer => Array.from(new Uint8Array(buffer), b => b.toString(16).padStart(2, '0')).join('');
export const b64 = buffer => btoa(String.fromCharCode(...new Uint8Array(buffer))).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
export const unb64 = text => Uint8Array.from(atob(text.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - text.length % 4) % 4)), c => c.charCodeAt(0));
export async function canonical(method, path, body, timestamp, nonce) {
  return [method.toUpperCase(), path, hex(await crypto.subtle.digest('SHA-256', bytes(body))), timestamp, nonce].join('\n');
}
export async function generateIdentity(name) {
  const keys = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign', 'verify']);
  const der = await crypto.subtle.exportKey('spki', keys.publicKey);
  const encoded = btoa(String.fromCharCode(...new Uint8Array(der)));
  const pem = `-----BEGIN PUBLIC KEY-----\n${encoded.match(/.{1,64}/g).join('\n')}\n-----END PUBLIC KEY-----\n`;
  return { id: hex(await crypto.subtle.digest('SHA-256', der)).slice(0, 32), name, pem, key: keys.privateKey, paired: false };
}
export async function signedHeaders(identity, method, path, body, timestamp = String(Math.floor(Date.now() / 1000)), nonce = b64(crypto.getRandomValues(new Uint8Array(24)))) {
  const payload = await canonical(method, path, body, timestamp, nonce);
  const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, identity.key, bytes(payload));
  return { 'Content-Type': 'application/json', 'X-Device-Id': identity.id, 'X-Timestamp': timestamp, 'X-Nonce': nonce, 'X-Signature': b64(signature) };
}
function rawSignature(der) {
  if (der[0] !== 48 || der[2] !== 2) throw Error('Invalid laptop proof');
  const length = der[3], start = 4 + length;
  if (der[start] !== 2) throw Error('Invalid laptop proof');
  const result = new Uint8Array(64);
  for (const [offset, part] of [[0, der.slice(4, start)], [32, der.slice(start + 2)]]) {
    const value = part.length === 33 && part[0] === 0 ? part.slice(1) : part;
    if (value.length > 32) throw Error('Invalid laptop proof');
    result.set(value, offset + 32 - value.length);
  }
  return result;
}
export async function verifyLaptop(result, identity, nonce) {
  const proof = result.proof, payload = proof?.payload;
  if (!payload || payload.device_id !== identity.id || payload.nonce !== nonce || payload.state !== result.state) throw Error('Laptop proof mismatch');
  const der = unb64(proof.public_key.replace(/-----[^-]+-----|\s/g, ''));
  if ('sha256:' + hex(await crypto.subtle.digest('SHA-256', der)) !== identity.fingerprint) throw Error('Laptop fingerprint mismatch');
  const key = await crypto.subtle.importKey('spki', der, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
  const encoded = JSON.stringify({ device_id: payload.device_id, nonce: payload.nonce, state: payload.state });
  if (!await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, rawSignature(unb64(proof.signature)), bytes(encoded))) throw Error('Laptop proof invalid');
}
export async function database(action, key, value) {
  const db = await new Promise((resolve, reject) => {
    const opening = indexedDB.open('friday-remote', 1);
    opening.onupgradeneeded = () => opening.result.createObjectStore('private');
    opening.onsuccess = () => resolve(opening.result);
    opening.onerror = () => reject(opening.error);
  });
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction('private', action === 'get' ? 'readonly' : 'readwrite');
      const store = transaction.objectStore('private');
      const request = action === 'get' ? store.get(key) : action === 'delete' ? store.delete(key) : store.put(value, key);
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error || Error('Storage unavailable'));
    });
  } finally { db.close(); }
}
