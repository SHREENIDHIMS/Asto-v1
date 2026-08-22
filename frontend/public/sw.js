const CACHE = "asto-shell-v2";
const SHELL_ASSETS = ["/", "/login/", "/offline.html"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkOnlyWithOffline(request));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put("/", copy));
          return response;
        })
        .catch(() =>
          caches.match(request).then((hit) => hit || caches.match("/"))
        )
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(
      (hit) =>
        hit ||
        fetch(request).then((response) => {
          if (response.ok && url.origin === self.location.origin) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
    )
  );
});

async function networkOnlyWithOffline(request) {
  try {
    const response = await fetch(request);
    // Cache.put() only supports GET requests — caching a POST (search,
    // login, mutations) throws and must be skipped.
    if (response.ok && request.method === "GET") {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(request, copy));
    }
    return response;
  } catch {
    const hit = await caches.match(request);
    if (hit) return hit;
    return new Response(
      JSON.stringify({ detail: "Offline. Please reconnect to continue." }),
      { status: 503, headers: { "Content-Type": "application/json" } }
    );
  }
}
