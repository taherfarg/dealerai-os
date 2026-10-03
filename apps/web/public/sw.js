// The app's service worker (docs/sales/07-frontend.md § 8). It keeps one page —
// what to show with no network — and an icon; never an API response, and never
// anything a customer said. It shows what is pushed and opens what is tapped.
const CACHE = "dealerai-shell-v2";
const SHELL = ["/offline.html", "/icon/192"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  // Only a page load that fails for want of a network gets the offline page.
  // Everything else — the API, the app's own files, images — is not ours to answer.
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match("/offline.html")));
});

self.addEventListener("push", (event) => {
  const said = event.data ? event.data.json() : {};
  event.waitUntil(
    self.registration.showNotification(said.title || "DealerAI", {
      body: said.body || undefined,
      tag: said.tag,
      data: { href: said.href || "/" },
      icon: "/icon/192",
      badge: "/icon/192",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const href = new URL(event.notification.data?.href || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => w.url === href);
      return open ? open.focus() : self.clients.openWindow(href);
    }),
  );
});
