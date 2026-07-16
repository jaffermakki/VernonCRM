// Intentionally minimal: this app's data (invoices, stock, repairs) must
// always be fresh, so we don't cache pages or API responses here. This
// service worker exists only to satisfy PWA "installable" requirements
// (Android/Chrome require a fetch handler to be registered).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
