/**
 * ORVault service worker — offline reading.
 *
 * Three caches with deliberately different lifetimes:
 *
 *  - orvault-offline-v1  User downloads: chapter metadata + every page image.
 *                        NEVER version-bumped and never cleared on activate —
 *                        this is the user's library on a plane, not a perf cache.
 *                        Written by src/lib/offline/manager.ts from the page,
 *                        read here.  Entries are only removed when the user
 *                        deletes a download.
 *  - orvault-shell-vN    HTML documents for pages that must open offline.
 *  - orvault-static-vN   /_next/static/* build assets (content-hashed, so
 *                        cache-first is always safe).
 *
 * RSC payload requests are deliberately NOT intercepted: when one fails,
 * Next's router falls back to a full browser navigation, which lands on the
 * navigation handler below and gets a cached document.  Serving a guessed
 * RSC payload instead would hydrate the wrong tree.
 */

const VERSION = "v1";
const STATIC_CACHE = `orvault-static-${VERSION}`;
const SHELL_CACHE = `orvault-shell-${VERSION}`;
const OFFLINE_CACHE = "orvault-offline-v1";
const OFFLINE_FALLBACK = "/offline";

// Kept in sync with manager.ts — cleanup must never delete the download cache.
const KEEP_CACHES = [STATIC_CACHE, SHELL_CACHE, OFFLINE_CACHE];

// Shell pages refreshed automatically whenever they're visited online, so the
// app opens and can navigate with no network at all.
const AUTO_SHELL_PATHS = [
  "/",
  "/offline",
  "/downloads",
  "/browse",
  "/my-list",
  "/updates",
  "/settings",
];

const STATIC_ASSETS = ["/manifest.json", "/icon-192.png", "/icon-512.png"];

function isChapterAsset(pathname) {
  return pathname.startsWith("/api/chapters/");
}

function isCover(pathname) {
  return pathname.startsWith("/api/covers/") || pathname.startsWith("/covers/");
}

function isStaticAsset(pathname) {
  return pathname.startsWith("/_next/static/") || STATIC_ASSETS.includes(pathname);
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const shell = await caches.open(SHELL_CACHE);
      // Best effort: a failed precache must not block installation, or a
      // transient blip leaves the user with no service worker at all.
      await Promise.all(
        [OFFLINE_FALLBACK, "/"].map(async (path) => {
          try {
            const res = await fetch(path, { credentials: "same-origin" });
            if (res.ok && !res.redirected) await shell.put(path, res);
          } catch {
            /* offline at install time — the runtime handler will fill this in */
          }
        })
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((n) => n.startsWith("orvault-") && !KEEP_CACHES.includes(n))
          .map((n) => caches.delete(n))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  let url;
  try {
    url = new URL(req.url);
  } catch {
    return;
  }
  if (url.origin !== self.location.origin) return;

  // Auth endpoints must always see the real network state — a cached session
  // response would leave the app thinking it's signed in after a sign-out.
  if (url.pathname.startsWith("/api/auth")) return;

  // See the header comment: let RSC requests fail so Next does a full nav.
  if (req.headers.has("RSC") || url.searchParams.has("_rsc")) return;

  if (isChapterAsset(url.pathname) || isCover(url.pathname)) {
    event.respondWith(downloadFirst(req));
    return;
  }

  if (isStaticAsset(url.pathname)) {
    event.respondWith(staticAsset(req));
    return;
  }

  if (req.mode === "navigate") {
    event.respondWith(navigation(req));
  }
});

/**
 * Downloaded chapter content wins over the network unconditionally: it is
 * byte-identical to what the server would send, and going to the network
 * first would stall every page load on a flaky connection.
 *
 * `ignoreSearch` matters — the reader's "reload images" button appends ?r=N
 * to bust the browser's error cache, and that must still resolve offline.
 */
async function downloadFirst(request) {
  const cache = await caches.open(OFFLINE_CACHE);
  const hit = await cache.match(request, { ignoreSearch: true });
  if (hit) return hit;

  try {
    return await fetch(request);
  } catch {
    return new Response(
      JSON.stringify({ error: "Offline and this chapter is not downloaded" }),
      { status: 503, headers: { "Content-Type": "application/json" } }
    );
  }
}

/**
 * Build assets are content-hashed, so cache-first is always correct.
 *
 * The download cache is checked first and separately: the manager pins the JS
 * and CSS a downloaded chapter's reader page needs into it, so a service
 * worker version bump (which clears the runtime static cache) can never leave
 * a downloaded chapter unreadable on a plane.
 */
async function staticAsset(request) {
  const pinned = await (await caches.open(OFFLINE_CACHE)).match(request);
  if (pinned) return pinned;

  const cache = await caches.open(STATIC_CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;

  const res = await fetch(request);
  if (res.ok) await cache.put(request, res.clone());
  return res;
}

async function navigation(request) {
  const url = new URL(request.url);
  const shell = await caches.open(SHELL_CACHE);

  try {
    const res = await fetch(request);
    // Redirected responses can't be replayed from a cache for a navigation
    // (the browser rejects them), and a redirect here means the login wall.
    if (res.ok && !res.redirected) {
      const downloads = await caches.open(OFFLINE_CACHE);
      const pinned = await downloads.match(url.pathname, { ignoreSearch: true });
      if (pinned) {
        // This document belongs to a download. Refresh the pinned copy and its
        // build assets, otherwise the version read offline drifts further
        // behind the deployed app with every release.
        await refreshPinned(downloads, url.pathname, res.clone());
      } else if (AUTO_SHELL_PATHS.includes(url.pathname)) {
        await shell.put(url.pathname, res.clone());
      }
    }
    return res;
  } catch {
    const downloads = await caches.open(OFFLINE_CACHE);
    const hit =
      (await downloads.match(url.pathname, { ignoreSearch: true })) ||
      (await shell.match(url.pathname, { ignoreSearch: true })) ||
      (await downloads.match(OFFLINE_FALLBACK)) ||
      (await shell.match(OFFLINE_FALLBACK));
    if (hit) return hit;

    return new Response(
      "<!doctype html><meta charset=utf-8><title>Offline</title>" +
        "<body style=\"font-family:system-ui;background:#0f0f0f;color:#eaeaea;padding:2rem\">" +
        "<h1>Offline</h1><p>This page isn't available offline.</p>",
      { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } }
    );
  }
}

/**
 * Replace a pinned document with a freshly fetched one and pin whatever build
 * assets it now references. Mirrors pinDocument/pinDocumentAssets in
 * src/lib/offline/manager.ts — the manager does this at download time, this
 * keeps it current afterwards.
 */
async function refreshPinned(downloads, pathname, response) {
  const html = await response.text();
  await downloads.put(
    pathname,
    new Response(html, {
      status: 200,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    })
  );
  const assets = new Set(html.match(/\/_next\/static\/[^"'\s\)]+/g) || []);
  for (const asset of assets) {
    if (await downloads.match(asset)) continue;
    try {
      const res = await fetch(asset);
      if (res.ok) await downloads.put(asset, res);
    } catch {
      /* the document still works from the previously pinned assets */
    }
  }
}
