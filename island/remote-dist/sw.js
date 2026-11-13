const CACHE = 'friday-remote-deb6b24b0ef0a73a';
const shell = ['./', './index.html', './app.js', './style.css', './manifest.webmanifest', './icon-192.png', './icon-512.png', './apple-touch-icon.png'];
self.addEventListener('install', event => event.waitUntil((async () => {
  const cache = await caches.open(CACHE);
  for (const name of shell) {
    const response = await fetch(new URL(name, self.registration.scope), {cache:'reload'});
    if (!response.ok || (name.endsWith('.js') && !response.headers.get('content-type')?.includes('javascript'))) throw Error('Shell unavailable');
    await cache.put(new URL(name, self.registration.scope), response);
  }
  await self.skipWaiting();
})()));
self.addEventListener('activate', event => event.waitUntil((async () => {
  for (const key of await caches.keys()) if (key.startsWith('friday-remote-') && key !== CACHE) await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || event.request.headers.has('X-Signature')) return;
  const url = new URL(event.request.url);
  if (!shell.some(name => new URL(name, self.registration.scope).href === url.href)) return;
  event.respondWith(caches.open(CACHE).then(async cache => await cache.match(event.request) || fetch(event.request)));
});
