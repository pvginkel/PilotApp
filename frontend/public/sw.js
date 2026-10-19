// Pilot's service worker, there so Chrome on Android installs the app to the home screen (F95);
// served from the root, its scope is the whole app. It caches nothing. It answers only a
// navigation the network does not, with one line, and never a request under /api/: sign-in, its
// callback and sign-out are navigations there.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate' || new URL(e.request.url).pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Pilot</title>'
    + '<p style="font-family:system-ui;margin:40px">Pilot is unreachable. Try again when you are back on the network.</p>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
