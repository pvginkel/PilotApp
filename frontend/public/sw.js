// Pilot's service worker, there so Chrome on Android installs the app to the home screen (F95)
// and to show the server's pushes (F94, F142); served from the root, its scope is the whole app.
// It caches nothing. It answers only a navigation the network does not, with one line, and never a
// request under /api/: sign-in, its callback and sign-out are navigations there.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate' || new URL(e.request.url).pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Pilot</title>'
    + '<p style="font-family:system-ui;margin:40px">Pilot is unreachable. Try again when you are back on the network.</p>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});

// A push shows under its `tag`, replacing what stands there: the server's JSON, `renotify` true
// for an alert. `renotify` false keeps quiet only a notification that replaces another, so an
// update is `silent` too, for where nothing stands under its tag any more, swiped or closed by the
// app. Nothing is pushed to dismiss: the app closes its notifications where it opens.
self.addEventListener('push', (e) => {
  const { title, body, tag, url, renotify } = e.data.json();
  e.waitUntil(self.registration.showNotification(title, {
    body, tag, renotify, silent: !renotify, icon: '/icon-192.png', data: { url },
  }));
});

// A tap brings the window last focused to the push's `url`, else opens the app there. The window
// is focused first, while the tap's permission to focus one lasts.
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(openAt(new URL(e.notification.data.url, self.location.origin).href));
});

async function openAt(url) {
  const [open] = await self.clients.matchAll({ type: 'window' });
  if (open === undefined) return self.clients.openWindow(url);
  const focused = await open.focus();
  return focused.navigate(url);
}
