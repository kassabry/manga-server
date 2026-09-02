/**
 * Offline download manager — runs on the page, not in the service worker.
 *
 * Everything a downloaded chapter needs to render with no network is written
 * into a single Cache Storage bucket that the service worker never clears:
 *
 *   /api/chapters/:id            chapter metadata JSON
 *   /api/chapters/:id/pages/:n   every page image (or EPUB chapter HTML)
 *   /read/:id                    the reader document itself
 *   /_next/static/...            the JS + CSS that document loads
 *   the series cover
 *
 * Pinning the document and its build assets is what makes a cold start work:
 * opening the app from the home screen in airplane mode has to serve real
 * HTML from somewhere, and Next's hashed chunks are useless if they were
 * evicted with the rest of the runtime cache.
 */

import {
  deleteChapterRecord,
  getAllChapters,
  getChapter,
  putChapter,
  type OfflineChapter,
} from "./db";

/** Must match OFFLINE_CACHE in public/sw.js. */
const OFFLINE_CACHE = "orvault-offline-v1";

/** Pages that must open with no network once anything has been downloaded. */
const PINNED_SHELL = ["/", "/downloads", "/offline"];

/** Concurrent page fetches. Enough to saturate wifi, gentle on a Pi. */
const CONCURRENCY = 4;

export interface ChapterMeta {
  id: string;
  number: number;
  title: string | null;
  pageCount: number;
  isEpub?: boolean;
  source: string | null;
  series: { id: string; title: string; slug: string };
  pages: { index: number; name: string; url: string }[];
}

export interface DownloadProgress {
  done: number;
  total: number;
}

export function isOfflineSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "caches" in window &&
    window.isSecureContext
  );
}

async function openCache(): Promise<Cache> {
  return caches.open(OFFLINE_CACHE);
}

/**
 * Ask the browser not to evict us under storage pressure. Without this a
 * multi-gigabyte download is fair game for eviction the moment the device gets
 * low on space — which would be discovered mid-flight.
 */
export async function requestPersistence(): Promise<boolean> {
  try {
    if (!navigator.storage?.persist) return false;
    if (await navigator.storage.persisted()) return true;
    return await navigator.storage.persist();
  } catch {
    return false;
  }
}

export async function storageEstimate(): Promise<{ usage: number; quota: number } | null> {
  try {
    const est = await navigator.storage?.estimate?.();
    if (!est) return null;
    return { usage: est.usage ?? 0, quota: est.quota ?? 0 };
  } catch {
    return null;
  }
}

/** Fetch a URL and store the exact bytes, returning how many there were. */
async function cacheUrl(
  cache: Cache,
  url: string,
  signal?: AbortSignal,
  { skipIfPresent = true } = {}
): Promise<number> {
  if (skipIfPresent) {
    const existing = await cache.match(url, { ignoreSearch: true });
    if (existing) {
      // Already stored by an earlier (possibly interrupted) run — count it so
      // the size total stays right when a download resumes.
      const blob = await existing.clone().blob();
      return blob.size;
    }
  }

  const res = await fetch(url, { credentials: "same-origin", signal });
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  // A body can only be read once, so buffer it and rebuild the response for
  // the cache — that also gives an exact byte count.
  const buf = await res.arrayBuffer();
  const contentType = res.headers.get("Content-Type") || "application/octet-stream";
  await cache.put(url, new Response(buf, { status: 200, headers: { "Content-Type": contentType } }));
  return buf.byteLength;
}

/**
 * Pull the build assets a document references so the reader page can boot
 * offline. Matches both the plain `src="/_next/static/..."` attributes and the
 * escaped copies inside Next's inline RSC payload.
 */
async function pinDocumentAssets(cache: Cache, html: string, signal?: AbortSignal) {
  const assets = new Set(html.match(/\/_next\/static\/[^"'\s\\)]+/g) ?? []);
  for (const asset of assets) {
    // One failed chunk should not fail the whole chapter download.
    await cacheUrl(cache, asset, signal).catch(() => 0);
  }
}

async function pinDocument(cache: Cache, path: string, signal?: AbortSignal) {
  const existing = await cache.match(path, { ignoreSearch: true });
  const res = await fetch(path, { credentials: "same-origin", signal });
  // A redirect means the login wall — caching it would serve the login page
  // in place of the reader forever after.
  if (!res.ok || res.redirected) {
    if (!existing) throw new Error(`Could not save ${path} for offline use`);
    return;
  }
  const html = await res.text();
  await cache.put(
    path,
    new Response(html, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } })
  );
  await pinDocumentAssets(cache, html, signal);
}

/** How long a shell pin is considered fresh, so a 200-chapter queue doesn't
 *  refetch three documents per chapter. */
const SHELL_PIN_TTL_MS = 10 * 60 * 1000;
let shellPinnedAt = 0;

/** Keep the app openable offline even when started from the home screen. */
export async function pinShell(signal?: AbortSignal, force = false): Promise<void> {
  if (!force && Date.now() - shellPinnedAt < SHELL_PIN_TTL_MS) return;
  const cache = await openCache();
  for (const path of PINNED_SHELL) {
    await pinDocument(cache, path, signal).catch(() => {});
  }
  shellPinnedAt = Date.now();
}

export async function isChapterDownloaded(chapterId: string): Promise<boolean> {
  return Boolean(await getChapter(chapterId));
}

export async function listDownloads(): Promise<OfflineChapter[]> {
  return getAllChapters();
}

/**
 * Download one chapter for offline reading. Safe to re-run: anything already
 * cached is skipped, so an interrupted download resumes rather than restarting.
 */
export async function downloadChapter(
  chapterId: string,
  opts: {
    signal?: AbortSignal;
    onProgress?: (p: DownloadProgress) => void;
    /** Cover URL the caller already has, saving a round trip. */
    coverPath?: string | null;
  } = {}
): Promise<OfflineChapter> {
  if (!isOfflineSupported()) {
    throw new Error("Offline downloads need a secure (https) connection");
  }
  const { signal, onProgress } = opts;
  const cache = await openCache();

  const metaUrl = `/api/chapters/${chapterId}`;
  const metaRes = await fetch(metaUrl, { credentials: "same-origin", signal });
  if (!metaRes.ok) {
    throw new Error(
      metaRes.status === 410
        ? "This chapter's file is missing from the server"
        : `Could not load chapter (HTTP ${metaRes.status})`
    );
  }
  const metaText = await metaRes.text();
  const meta: ChapterMeta = JSON.parse(metaText);
  await cache.put(
    metaUrl,
    new Response(metaText, { status: 200, headers: { "Content-Type": "application/json" } })
  );

  const total = meta.pages.length;
  let done = 0;
  let bytes = 0;
  onProgress?.({ done, total });

  // Fixed worker pool over the page list — a plain Promise.all would open one
  // connection per page and get throttled on long webtoon chapters.
  let cursor = 0;
  const failures: string[] = [];
  const worker = async () => {
    while (cursor < total) {
      const page = meta.pages[cursor++];
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      try {
        // Deliberately two statements: `bytes += await …` reads `bytes` before
        // awaiting, so with four workers in flight every one of them reads the
        // same stale total and the last write wins.
        const size = await cacheUrl(cache, page.url, signal);
        bytes += size;
      } catch (err) {
        if ((err as Error).name === "AbortError") throw err;
        failures.push(page.url);
      }
      done++;
      onProgress?.({ done, total });
    }
  };
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, total || 1) }, worker));

  if (failures.length > 0) {
    throw new Error(
      `${failures.length} of ${total} page${total === 1 ? "" : "s"} failed — try again`
    );
  }

  if (opts.coverPath) await cacheUrl(cache, opts.coverPath, signal).catch(() => 0);
  await pinDocument(cache, `/read/${chapterId}`, signal);
  await pinShell(signal);

  const record: OfflineChapter = {
    id: chapterId,
    seriesId: meta.series.id,
    seriesTitle: meta.series.title,
    seriesSlug: meta.series.slug,
    coverPath: opts.coverPath ?? null,
    number: meta.number,
    title: meta.title,
    source: meta.source,
    pageCount: total,
    isEpub: Boolean(meta.isEpub),
    bytes,
    downloadedAt: Date.now(),
  };
  await putChapter(record);
  return record;
}

/**
 * Remove one chapter's data. Shared assets (build chunks) are left alone; the
 * cover goes only when this was the series' last downloaded chapter.
 */
export async function removeChapter(chapterId: string): Promise<void> {
  const record = await getChapter(chapterId);
  const cache = await openCache();

  await cache.delete(`/api/chapters/${chapterId}`, { ignoreSearch: true });
  const pageCount = record?.pageCount ?? 0;
  for (let i = 0; i < pageCount; i++) {
    await cache.delete(`/api/chapters/${chapterId}/pages/${i}`, { ignoreSearch: true });
  }
  await cache.delete(`/read/${chapterId}`, { ignoreSearch: true });
  await deleteChapterRecord(chapterId);

  if (!record) return;
  const remaining = (await getAllChapters()).filter((c) => c.seriesId === record.seriesId);
  if (remaining.length === 0 && record.coverPath) {
    await cache.delete(record.coverPath, { ignoreSearch: true });
  }
}

/**
 * Drop the half-written cache entries left by a cancelled download.
 *
 * The chapter never made it into the IndexedDB index, so its page count is
 * unknown — scan the cache by key prefix instead of guessing an upper bound.
 */
export async function discardPartial(chapterId: string): Promise<void> {
  const cache = await openCache();
  const prefix = `/api/chapters/${chapterId}`;
  for (const req of await cache.keys()) {
    const path = new URL(req.url).pathname;
    if (path === prefix || path.startsWith(`${prefix}/`)) await cache.delete(req);
  }
  await cache.delete(`/read/${chapterId}`, { ignoreSearch: true });
}

export async function removeSeries(seriesId: string): Promise<void> {
  const chapters = (await getAllChapters()).filter((c) => c.seriesId === seriesId);
  for (const ch of chapters) await removeChapter(ch.id);
}

/** Delete every download and the cache behind them. */
export async function removeAll(): Promise<void> {
  for (const ch of await getAllChapters()) await deleteChapterRecord(ch.id);
  await caches.delete(OFFLINE_CACHE);
}

export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 MB";
  const mb = bytes / 1024 / 1024;
  if (mb < 1) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (mb < 1024) return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}
