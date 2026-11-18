import { signedHeaders, verifyLaptop } from './signing.mjs';
// Tailscale Serve maps public / to the bridge's /remote. Direct bridge uses /remote/.
const prefix = location.pathname.startsWith('/remote/') ? '/remote' : '';
export async function request(identity, method, operation, body, options = {}) {
  const text = body === undefined ? '' : JSON.stringify(body);
  const canonicalPath = '/remote/v1/' + operation;
  const headers = await signedHeaders(identity, method, canonicalPath, text);
  let response;
  try { response = await fetch(prefix + '/v1/' + operation, {
    method, headers, body: text || undefined, cache: 'no-store', credentials: 'same-origin',
    signal: options.signal || AbortSignal.timeout(45000), redirect: 'error',
  }); } catch (cause) {
    const error = Error('Laptop unreachable. Safe actions can wait for reconnection.', { cause });
    error.networkUnavailable = true; throw error;
  }
  if (!response.ok) {
    if ([502, 503, 504].includes(response.status)) {
      const error = Error('Laptop service unavailable. Safe actions will wait for reconnection.');
      error.networkUnavailable = true; throw error;
    }
    const error = Error('Request refused. Check remote access on the laptop.');
    error.requestRefused = true; throw error;
  }
  if (options.stream) return response;
  let value;
  try { value = await response.json(); }
  catch (cause) {
    if (!(cause instanceof SyntaxError)) {
      const error = Error('Laptop reply interrupted. Safe actions keep their request IDs.', { cause });
      error.networkUnavailable = true; throw error;
    }
    throw cause;
  }
  if (operation.startsWith('pair')) await verifyLaptop(value, identity, headers['X-Nonce']);
  return value;
}
export async function readStream(response, onEvent) {
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replaceAll('\r\n', '\n');
      if (buffer.length > 131072) throw Error('Stream too large');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        const lines = block.split('\n');
        const name = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
        const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
        if (name && data) await onEvent(name, JSON.parse(data));
      }
      if (done) break;
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
