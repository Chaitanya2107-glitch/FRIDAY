import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
// @ts-ignore Browser ES module shared with the phone bundle.
import { canonical, generateIdentity, signedHeaders, unb64, bytes } from '../remote/signing.mjs';

const vectors = JSON.parse(readFileSync(new URL('../../tests/remote_vectors.json', import.meta.url), 'utf8'));
for (const vector of vectors) test(`remote canonical + Python signature ${vector.path}`, async () => {
  assert.equal(await canonical(vector.method, vector.path, vector.body, vector.timestamp, vector.nonce), vector.canonical);
  const der = unb64(vector.public_key.replace(/-----[^-]+-----|\s/g, ''));
  const key = await crypto.subtle.importKey('spki', der, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
  assert.equal(await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, unb64(vector.signature), bytes(vector.canonical)), true);
});
test('phone private key is non-extractable, signs P1363, and survives structured clone', async () => {
  const identity = await generateIdentity('Test phone');
  assert.equal(identity.key.extractable, false);
  await assert.rejects(crypto.subtle.exportKey('pkcs8', identity.key));
  const restored = structuredClone(identity);
  assert.equal(restored.key.extractable, false);
  const vector = vectors[0];
  const headers = await signedHeaders(restored, vector.method, vector.path, vector.body, vector.timestamp, vector.nonce);
  assert.equal(unb64(headers['X-Signature']).length, 64);
  const key = await crypto.subtle.importKey('spki', unb64(identity.pem.replace(/-----[^-]+-----|\s/g, '')), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
  assert.equal(await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, unb64(headers['X-Signature']), bytes(vector.canonical)), true);
});
