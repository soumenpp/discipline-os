// Discipline OS — Service Worker v2
// Handles background push notifications

const CACHE = 'discipline-os-v2';

self.addEventListener('install', e => {
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(clients.claim());
});

// ── PUSH NOTIFICATION HANDLER ──────────────────────────────
self.addEventListener('push', e => {
  let data = { title: '🔥 Discipline OS', body: 'You have a new update', icon: '🔱', url: '/' };
  try {
    if (e.data) data = { ...data, ...e.data.json() };
  } catch(err) {
    if (e.data) data.body = e.data.text();
  }

  const options = {
    body: data.body,
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    tag: 'discipline-os',           // replaces previous notification
    renotify: true,
    vibrate: [200, 100, 200],
    data: { url: data.url || '/' },
    actions: [
      { action: 'open',   title: '📲 Open App' },
      { action: 'dismiss', title: '✕ Dismiss'  }
    ]
  };

  e.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// ── NOTIFICATION CLICK ─────────────────────────────────────
self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'dismiss') return;

  const url = e.notification.data?.url || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if (c.url.includes(self.location.origin)) {
          c.focus();
          c.navigate(url);
          return;
        }
      }
      return clients.openWindow(url);
    })
  );
});
