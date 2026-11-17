// Service worker for the Nexus web app: lets it open offline once installed to the home screen.
//
// The page (index.html) is fetched network-first, so students get your latest build whenever
// they are online; if the network is slow or gone it falls back to the copy saved last time.
// Cytoscape, the fonts and the icons rarely change, so they are served from the cache and
// refreshed in the background.
//
// You never need to edit this file when you rebuild the map. Bump VERSION only if you change
// the list in CORE or want every installed copy to throw away its cache.
const VERSION = "nexus-v1";
const CORE = [
  "./",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/apple-touch-icon.png",
  "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js",
];
const CACHED_HOSTS = ["cdnjs.cloudflare.com", "fonts.googleapis.com", "fonts.gstatic.com"];
const NETWORK_TIMEOUT_MS = 4000;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(VERSION).then((cache) =>
      // One failed download (say, the CDN is blocked on a school network) should not stop the
      // rest from being saved.
      Promise.all(CORE.map((url) => cache.add(url).catch(() => {})))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const inScope = url.origin === self.location.origin && url.pathname.startsWith(new URL(self.registration.scope).pathname);

  if (req.mode === "navigate" && inScope) {
    event.respondWith(networkFirst(req));
  } else if (inScope || CACHED_HOSTS.includes(url.hostname)) {
    event.respondWith(staleWhileRevalidate(event, req));
  }
});

async function networkFirst(req) {
  const cache = await caches.open(VERSION);
  try {
    const res = await withTimeout(fetch(req), NETWORK_TIMEOUT_MS);
    if (res.ok) cache.put("./", res.clone());
    return res;
  } catch (e) {
    return (await cache.match("./")) || (await cache.match(req)) || Response.error();
  }
}

async function staleWhileRevalidate(event, req) {
  const cache = await caches.open(VERSION);
  const cached = await cache.match(req, { ignoreVary: true });
  const fresh = fetch(req)
    .then((res) => {
      if (res.ok || res.type === "opaque") cache.put(req, res.clone());
      return res;
    })
    .catch(() => cached);
  if (cached) {
    event.waitUntil(fresh);
    return cached;
  }
  return fresh;
}

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("timeout")), ms);
    promise.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
}
