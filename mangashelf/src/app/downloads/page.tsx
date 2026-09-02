"use client";

/**
 * Offline library.
 *
 * Everything here comes from IndexedDB and Cache Storage, never the server —
 * this is the page you land on in airplane mode, so it has to render with no
 * network at all.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useOffline } from "@/components/offline/OfflineProvider";
import { formatBytes, storageEstimate } from "@/lib/offline/manager";
import type { OfflineChapter } from "@/lib/offline/db";

interface SeriesGroup {
  seriesId: string;
  title: string;
  coverPath: string | null;
  chapters: OfflineChapter[];
  bytes: number;
}

export default function DownloadsPage() {
  const {
    supported,
    blocker,
    online,
    downloaded,
    queue,
    active,
    remove,
    removeSeriesDownloads,
    clearEverything,
    refresh,
  } = useOffline();
  const [storage, setStorage] = useState<{ usage: number; quota: number } | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void storageEstimate().then(setStorage);
  }, [downloaded]);

  const groups = useMemo<SeriesGroup[]>(() => {
    const map = new Map<string, SeriesGroup>();
    for (const ch of Object.values(downloaded)) {
      let group = map.get(ch.seriesId);
      if (!group) {
        group = {
          seriesId: ch.seriesId,
          title: ch.seriesTitle,
          coverPath: ch.coverPath,
          chapters: [],
          bytes: 0,
        };
        map.set(ch.seriesId, group);
      }
      group.chapters.push(ch);
      group.bytes += ch.bytes;
      if (!group.coverPath && ch.coverPath) group.coverPath = ch.coverPath;
    }
    const list = Array.from(map.values());
    for (const g of list) g.chapters.sort((a, b) => a.number - b.number);
    return list.sort((a, b) => a.title.localeCompare(b.title));
  }, [downloaded]);

  const totalBytes = groups.reduce((sum, g) => sum + g.bytes, 0);
  const totalChapters = Object.keys(downloaded).length;

  if (!supported) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Downloads</h1>
        <div className="rounded-xl border border-yellow-700/40 bg-yellow-900/20 p-4 text-sm text-yellow-300">
          <p className="font-medium">Offline downloads are not available here.</p>
          {blocker === "registration-failed" ? (
            <p className="mt-2 text-yellow-300/80">
              The browser refused to start this app&apos;s service worker. Reload the page;
              if it keeps failing, the browser may have service workers disabled (some
              private-browsing modes do).
            </p>
          ) : (
            <p className="mt-2 text-yellow-300/80">
              Browsers only allow offline storage on a secure origin. Open the app over{" "}
              <code className="rounded bg-black/30 px-1">https://</code> (or at{" "}
              <code className="rounded bg-black/30 px-1">http://localhost</code> on this
              machine) and this page will start working.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Downloads</h1>
          <p className="mt-1 text-sm text-text-secondary">
            {totalChapters === 0
              ? "Nothing saved yet — use the Offline button on any series."
              : `${totalChapters} chapter${totalChapters === 1 ? "" : "s"} across ${
                  groups.length
                } series · ${formatBytes(totalBytes)}`}
          </p>
        </div>
        {totalChapters > 0 && (
          <button
            onClick={() => {
              if (confirm("Remove every downloaded chapter from this device?")) {
                void clearEverything();
              }
            }}
            className="rounded-lg border border-border px-3 py-2 text-sm text-text-secondary hover:border-red-500/60 hover:text-red-400"
          >
            Remove all
          </button>
        )}
      </div>

      {!online && (
        <div className="rounded-xl border border-accent/40 bg-accent/10 px-4 py-3 text-sm text-accent">
          You&apos;re offline. Only the chapters listed here can be opened.
        </div>
      )}

      {storage && storage.quota > 0 && (
        <div className="rounded-xl border border-border bg-bg-card p-4">
          <div className="flex items-center justify-between text-xs text-text-secondary">
            <span>Device storage used by this app</span>
            <span>
              {formatBytes(storage.usage)} of {formatBytes(storage.quota)}
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-bg-hover">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${Math.min(100, (storage.usage / storage.quota) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {(active || queue.length > 0) && (
        <div className="rounded-xl border border-border bg-bg-card p-4">
          <h2 className="text-sm font-semibold">In progress</h2>
          {active && (
            <p className="mt-1 text-xs text-text-secondary">
              {active.item.seriesTitle} · Ch. {active.item.number}
              {active.progress.total > 0 &&
                ` — ${active.progress.done}/${active.progress.total} pages`}
            </p>
          )}
          {queue.length > 1 && (
            <p className="mt-1 text-xs text-text-secondary">
              {queue.length - 1} more chapter{queue.length - 1 === 1 ? "" : "s"} waiting
            </p>
          )}
        </div>
      )}

      {groups.length === 0 && !active && (
        <div className="rounded-xl border border-dashed border-border py-12 text-center text-text-secondary">
          <p className="text-sm">No downloads yet.</p>
          <p className="mt-1 text-xs">
            Open a series and choose <span className="text-text-primary">Offline → Next 10 unread</span>{" "}
            before you lose signal.
          </p>
        </div>
      )}

      <div className="space-y-3">
        {groups.map((group) => {
          const isOpen = expanded[group.seriesId] ?? false;
          return (
            <div key={group.seriesId} className="rounded-xl border border-border bg-bg-card">
              <div className="flex items-center gap-3 p-3">
                {group.coverPath ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={group.coverPath}
                    alt=""
                    className="h-20 w-14 shrink-0 rounded object-cover"
                  />
                ) : (
                  <div className="h-20 w-14 shrink-0 rounded bg-bg-hover" />
                )}

                <div className="min-w-0 flex-1">
                  {/* Plain text when offline: the series page needs the server. */}
                  {online ? (
                    <Link
                      href={`/series/${group.seriesId}`}
                      className="block truncate font-medium hover:text-accent"
                    >
                      {group.title}
                    </Link>
                  ) : (
                    <span className="block truncate font-medium">{group.title}</span>
                  )}
                  <p className="mt-0.5 text-xs text-text-secondary">
                    {group.chapters.length} chapter{group.chapters.length === 1 ? "" : "s"} ·{" "}
                    {formatBytes(group.bytes)}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Link
                      href={`/read/${group.chapters[0].id}`}
                      className="rounded-lg bg-accent px-3 py-1 text-xs font-medium text-white hover:bg-accent-hover"
                    >
                      Read Ch. {group.chapters[0].number}
                    </Link>
                    <button
                      onClick={() => setExpanded((p) => ({ ...p, [group.seriesId]: !isOpen }))}
                      className="rounded-lg border border-border px-3 py-1 text-xs text-text-secondary hover:border-accent hover:text-accent"
                    >
                      {isOpen ? "Hide chapters" : "Show chapters"}
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Remove all downloaded chapters of ${group.title}?`)) {
                          void removeSeriesDownloads(group.seriesId);
                        }
                      }}
                      className="rounded-lg border border-border px-3 py-1 text-xs text-text-secondary hover:border-red-500/60 hover:text-red-400"
                    >
                      Remove
                    </button>
                  </div>
                </div>
              </div>

              {isOpen && (
                <div className="max-h-72 overflow-y-auto border-t border-border">
                  {group.chapters.map((ch) => (
                    <div
                      key={ch.id}
                      className="flex items-center justify-between gap-3 border-b border-border/50 px-3 py-2 last:border-b-0"
                    >
                      <Link
                        href={`/read/${ch.id}`}
                        className="min-w-0 flex-1 truncate text-sm hover:text-accent"
                      >
                        Chapter {ch.number}
                        {ch.title && (
                          <span className="text-text-secondary"> — {ch.title}</span>
                        )}
                      </Link>
                      <span className="shrink-0 text-xs text-text-secondary">
                        {ch.pageCount} pages · {formatBytes(ch.bytes)}
                      </span>
                      <button
                        onClick={() => void remove(ch.id)}
                        title="Remove this chapter"
                        className="shrink-0 rounded p-1 text-text-secondary/50 hover:text-red-400"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.6}>
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M9 7V4a1 1 0 011-1h4a1 1 0 011 1v3M4 7h16"
                          />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
