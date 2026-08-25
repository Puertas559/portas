const CACHE_VERSION = 'hg-radar-industrial-v16-3';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const STATIC_ASSETS = [
  '/static/pwa.css',
  '/static/pwa.js',
  '/static/hg-group-logo.png',
  '/static/pwa-icon-192.png',
  '/static/pwa-icon-512.png',
  '/static/pwa-maskable-512.png',
  '/static/apple-touch-icon.png',
  '/static/offline.html'
];
self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => (key.startsWith('hg-radar-') || key.startsWith('hg-radar-industrial-')) && key !== STATIC_CACHE)
      .map((key) => caches.delete(key))
  )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) { event.respondWith(fetch(request)); return; }
  if (url.pathname.startsWith('/static/')) {
    // Network-first evita CSS/JS antigo após deploy; cache apenas como fallback offline.
    event.respondWith(fetch(request).then((response) => {
      if (response.ok) caches.open(STATIC_CACHE).then((cache) => cache.put(request, response.clone()));
      return response;
    }).catch(() => caches.match(request)));
    return;
  }
  if (request.mode === 'navigate') event.respondWith(fetch(request).catch(() => caches.match('/static/offline.html')));
});
