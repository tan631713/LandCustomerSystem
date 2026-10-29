const CACHE_NAME = "land-customer-mobile-v26";
const APP_SHELL = [
  "/mobile/",
  "/mobile/index.html",
  "/mobile/styles.css",
  "/mobile/field-visit.js?v=2",
  "/mobile/app.js?v=26",
  "/mobile/manifest.webmanifest",
  "/mobile/app-icon.png",
  "/mobile/og.png"
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname === "/health") return;
  if (!url.pathname.startsWith("/mobile/")) return;

  event.respondWith(
    fetch(event.request, { cache: "no-store" }).then(response => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
      }
      return response;
    }).catch(() => caches.match(event.request))
  );
});
