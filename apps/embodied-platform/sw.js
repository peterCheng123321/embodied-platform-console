const CACHE = 'embodied-platform-v22';
const ASSETS = [
  './',
  './index.html',
  './assets/embodied-platform.css?v=22',
  './assets/embodied-platform.js?v=21',
  './assets/manifest.webmanifest',
  './assets/icon.svg',
  './fixtures/demo-state.json',
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith('embodied-platform-') && key !== CACHE)
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // NEVER intercept media (video/audio) or byte-range requests. Routing a media
  // element's range request through the SW (event.respondWith(fetch(...))) breaks
  // <video> streaming/seeking in Chrome — the media stack stalls at readyState 0.
  // Returning without respondWith lets the browser's native range machinery handle
  // it directly against the network.
  if (
    req.destination === 'video'
    || req.destination === 'audio'
    || req.headers.has('range')
    || /\.(mp4|webm|ogg|mov|m4v)(\?|$)/i.test(req.url)
  ) {
    return;
  }
  // App-shell fallback: navigations request the mount path (e.g. '/app/'), which
  // never URL-matches the precached './index.html' entry. Serve the cached shell
  // for any navigation when the network is down so the SPA still boots offline.
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('./index.html')));
    return;
  }
  event.respondWith(fetch(req).catch(() => caches.match(req)));
});
