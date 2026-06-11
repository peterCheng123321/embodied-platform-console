const CACHE = 'embodied-platform-v15';
const ASSETS = [
  './index.html',
  './assets/embodied-platform.css?v=14',
  './assets/embodied-platform.js?v=14',
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
  event.respondWith(fetch(req).catch(() => caches.match(req)));
});
