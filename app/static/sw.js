/* CartFlow service worker — installability plus an honest offline state.
 *
 * SCOPE OF WHAT IS CACHED. Only the app's own static assets (CSS, fonts, icons)
 * and one offline page. Pages are NOT cached: almost every page here renders
 * differently for whoever is signed in — messages, orders, a seller's drafts —
 * and a cached HTML document is served to the next person who opens the app on
 * that device. Static bytes are the same for everybody, so they are safe.
 *
 * NAVIGATIONS ARE NETWORK-FIRST. A cached shell would show prices and message
 * counts from whenever the cache was written, which in a marketplace is worse
 * than showing nothing. So a page that cannot be fetched shows the offline card
 * instead of a stale copy.
 *
 * Bump VERSION to retire a cache. The activate handler deletes every cache that
 * does not match, so old assets cannot accumulate across deploys.
 */
const VERSION = 'cartflow-v2';

const PRECACHE = [
  '/static/css/tailwind.css',
  '/static/css/cartflow-ui.css',
  '/static/css/fonts.css',
  // The landing page's own stylesheet and script. Cached with the rest of the
  // shell so /welcome — the first screen an installed app may open, via the
  // manifest's start URL — paints from cache on a cold, offline launch. The
  // Google sign-in script is NOT precached: it is only fetched on a tap.
  '/static/css/cartflow-landing.css',
  '/static/js/cartflow-landing.js',
  '/static/images/favicon-192.png',
  '/static/images/favicon.png',
  '/static/images/logo-icon.png',
  '/manifest.webmanifest',
  '/static/offline.html',
];

const OFFLINE_PAGE = '/static/offline.html';

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(VERSION);
      // Individually, not addAll: one missing file must not fail the whole
      // install and leave the app permanently unregistered.
      await Promise.all(
        PRECACHE.map((url) => cache.add(url).catch(() => undefined))
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  // Anything off-origin (Cloudinary images, for instance) is left alone.
  if (url.origin !== self.location.origin) return;
  // API responses are per-account and must never come from a cache.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          return await fetch(request);
        } catch (err) {
          const cache = await caches.open(VERSION);
          const offline = await cache.match(OFFLINE_PAGE);
          return offline || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
        }
      })()
    );
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    // Stale-while-revalidate: paint from cache immediately, then refresh it so
    // the next load has this deploy's CSS.
    event.respondWith(
      (async () => {
        const cache = await caches.open(VERSION);
        const cached = await cache.match(request);
        const network = fetch(request)
          .then((response) => {
            if (response.ok) cache.put(request, response.clone());
            return response;
          })
          .catch(() => undefined);
        return cached || (await network) || Response.error();
      })()
    );
  }
});
