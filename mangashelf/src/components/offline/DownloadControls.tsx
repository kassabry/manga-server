"use client";

/**
 * Download affordances shared by the series page and the reader.
 *
 * States a chapter can be in, and what each looks like:
 *   not downloaded  outline arrow, tap to queue
 *   queued          dimmed arrow with a dot, tap to drop from the queue
 *   downloading     ring showing pages fetched, tap to cancel
 *   downloaded      filled green check, tap to delete
 *   failed          red badge with the reason in the tooltip, tap to retry
 */

import { useMemo, useState } from "react";
import { useOffline, type QueueItem } from "./OfflineProvider";
import { formatBytes } from "@/lib/offline/manager";

interface ChapterLike {
  id: string;
  number: number;
}

function useChapterState(chapterId: string) {
  const { downloaded, queue, active, errors } = useOffline();
  return useMemo(() => {
    if (active?.item.chapterId === chapterId) {
      const { done, total } = active.progress;
      return {
        state: "downloading" as const,
        fraction: total > 0 ? done / total : 0,
        label: total > 0 ? `${done}/${total}` : "Starting…",
      };
    }
    if (queue.some((q) => q.chapterId === chapterId)) {
      return { state: "queued" as const, fraction: 0, label: "Queued" };
    }
    if (downloaded[chapterId]) {
      return {
        state: "done" as const,
        fraction: 1,
        label: formatBytes(downloaded[chapterId].bytes),
      };
    }
    if (errors[chapterId]) {
      return { state: "error" as const, fraction: 0, label: errors[chapterId] };
    }
    return { state: "idle" as const, fraction: 0, label: "Download for offline" };
  }, [chapterId, downloaded, queue, active, errors]);
}

/** Per-chapter download toggle. */
export function DownloadButton({
  chapter,
  seriesId,
  seriesTitle,
  coverPath,
  className = "",
  tone = "default",
}: {
  chapter: ChapterLike;
  seriesId: string;
  seriesTitle: string;
  coverPath?: string | null;
  className?: string;
  /** "reader" swaps the idle colour for the dark reader toolbar. */
  tone?: "default" | "reader";
}) {
  const { supported, enqueue, dequeue, remove } = useOffline();
  const { state, fraction, label } = useChapterState(chapter.id);

  if (!supported) return null;

  const item: QueueItem = {
    chapterId: chapter.id,
    seriesId,
    seriesTitle,
    number: chapter.number,
    coverPath,
  };

  const onClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (state === "done") {
      void remove(chapter.id);
    } else if (state === "queued" || state === "downloading") {
      dequeue(chapter.id);
    } else {
      enqueue([item]);
    }
  };

  const title =
    state === "done"
      ? `Downloaded (${label}) — tap to remove`
      : state === "downloading"
      ? `Downloading ${label} — tap to cancel`
      : state === "queued"
      ? "Queued — tap to cancel"
      : state === "error"
      ? `${label} — tap to retry`
      : label;

  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className={`relative shrink-0 rounded p-1 transition-colors ${
        state === "done"
          ? "text-green-500 hover:text-red-400"
          : state === "error"
          ? "text-red-400 hover:text-red-300"
          : state === "downloading" || state === "queued"
          ? "text-accent"
          : tone === "reader"
          ? "text-white/70 hover:text-white"
          : "text-text-secondary/40 hover:text-accent"
      } ${className}`}
    >
      {state === "downloading" ? (
        <ProgressRing fraction={fraction} />
      ) : state === "done" ? (
        <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
          <path
            fillRule="evenodd"
            d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z"
            clipRule="evenodd"
          />
        </svg>
      ) : (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v11m0 0l-4-4m4 4l4-4M4 19h16" />
        </svg>
      )}
      {state === "queued" && (
        <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-accent" />
      )}
    </button>
  );
}

function ProgressRing({ fraction }: { fraction: number }) {
  const radius = 7;
  const circumference = 2 * Math.PI * radius;
  return (
    <svg className="h-4 w-4 -rotate-90" viewBox="0 0 18 18">
      <circle cx="9" cy="9" r={radius} fill="none" stroke="currentColor" strokeWidth="2" opacity="0.2" />
      <circle
        cx="9"
        cy="9"
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - Math.min(1, Math.max(0, fraction)))}
      />
    </svg>
  );
}

/**
 * Series-level download menu: bulk actions plus a running count.
 *
 * "Next 10 unread" is the option that actually matters before a flight — the
 * whole-series option exists but a 400-chapter manhwa is several gigabytes,
 * so the estimate is spelled out before anything is queued.
 */
export function SeriesDownloadMenu({
  seriesId,
  seriesTitle,
  coverPath,
  chapters,
  isRead,
}: {
  seriesId: string;
  seriesTitle: string;
  coverPath?: string | null;
  chapters: ChapterLike[];
  /** True when the chapter is already finished, so bulk actions can skip it. */
  isRead: (chapterId: string) => boolean;
}) {
  const { supported, downloaded, queue, enqueue, removeSeriesDownloads } = useOffline();
  const [open, setOpen] = useState(false);

  const downloadedHere = chapters.filter((c) => downloaded[c.id]);
  const queuedHere = chapters.filter((c) => queue.some((q) => q.chapterId === c.id));
  const bytesHere = downloadedHere.reduce((sum, c) => sum + (downloaded[c.id]?.bytes ?? 0), 0);

  if (!supported) return null;

  const toItem = (c: ChapterLike): QueueItem => ({
    chapterId: c.id,
    seriesId,
    seriesTitle,
    number: c.number,
    coverPath,
  });

  const pending = chapters.filter((c) => !downloaded[c.id]);
  const unread = pending.filter((c) => !isRead(c.id)).sort((a, b) => a.number - b.number);

  const queueAndClose = (items: ChapterLike[]) => {
    setOpen(false);
    if (items.length > 0) enqueue(items.map(toItem));
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition ${
          open
            ? "border-accent text-accent"
            : downloadedHere.length > 0
            ? "border-green-700/50 bg-green-900/20 text-green-400"
            : "border-border bg-bg-card text-text-primary hover:border-accent"
        }`}
        title="Download chapters for offline reading"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v11m0 0l-4-4m4 4l4-4M4 19h16" />
        </svg>
        {downloadedHere.length > 0 ? `${downloadedHere.length} offline` : "Offline"}
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-xl border border-border bg-bg-secondary shadow-xl">
          <div className="border-b border-border px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
              Save for offline
            </span>
            <p className="mt-1 text-[11px] text-text-secondary">
              {downloadedHere.length} of {chapters.length} downloaded
              {bytesHere > 0 && ` · ${formatBytes(bytesHere)}`}
              {queuedHere.length > 0 && ` · ${queuedHere.length} queued`}
            </p>
          </div>

          <div className="p-1.5">
            <MenuAction
              label="Next 10 unread"
              hint={`${Math.min(10, unread.length)} chapter${unread.length === 1 ? "" : "s"}`}
              disabled={unread.length === 0}
              onClick={() => queueAndClose(unread.slice(0, 10))}
            />
            <MenuAction
              label="All unread"
              hint={`${unread.length} chapter${unread.length === 1 ? "" : "s"}`}
              disabled={unread.length === 0}
              onClick={() => queueAndClose(unread)}
            />
            <MenuAction
              label="Everything"
              hint={`${pending.length} chapter${pending.length === 1 ? "" : "s"}`}
              disabled={pending.length === 0}
              onClick={() => {
                if (
                  pending.length > 25 &&
                  !confirm(
                    `Download ${pending.length} chapters? On a slow connection this can take a while and use several GB of storage.`
                  )
                ) {
                  return;
                }
                queueAndClose(pending);
              }}
            />
          </div>

          {downloadedHere.length > 0 && (
            <div className="border-t border-border p-1.5">
              <MenuAction
                label="Remove downloads"
                hint={formatBytes(bytesHere)}
                destructive
                onClick={() => {
                  setOpen(false);
                  void removeSeriesDownloads(seriesId);
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MenuAction({
  label,
  hint,
  onClick,
  disabled = false,
  destructive = false,
}: {
  label: string;
  hint?: string;
  onClick: () => void;
  disabled?: boolean;
  destructive?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-sm transition disabled:opacity-35 ${
        destructive
          ? "text-red-400 hover:bg-red-500/10"
          : "text-text-primary hover:bg-bg-hover"
      }`}
    >
      <span>{label}</span>
      {hint && <span className="text-xs text-text-secondary">{hint}</span>}
    </button>
  );
}

/** Compact banner shown while a bulk download is running. */
export function DownloadQueueBanner() {
  const { active, queue, cancelAll } = useOffline();
  if (!active) return null;

  const { done, total } = active.progress;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="sticky bottom-0 z-40 border-t border-border bg-bg-secondary/95 px-4 py-2 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs text-text-primary">
            Downloading {active.item.seriesTitle} · Ch. {active.item.number}
            {total > 0 && ` — ${done}/${total} pages`}
            {queue.length > 1 && ` · ${queue.length - 1} more queued`}
          </p>
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-bg-hover">
            <div
              className="h-full rounded-full bg-accent transition-[width]"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        <button
          type="button"
          onClick={cancelAll}
          className="shrink-0 rounded-lg border border-border px-2.5 py-1 text-xs text-text-secondary hover:border-red-500/60 hover:text-red-400"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
