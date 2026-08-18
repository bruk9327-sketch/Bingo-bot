self.addEventListener('install', (e) => {
  console.log('[Service Worker] Installed');
});

self.addEventListener('fetch', (e) => {
  // Basic fetch handler to keep PWA criteria met
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
