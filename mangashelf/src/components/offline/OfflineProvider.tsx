"use client";

/**
 * Registers the service worker and owns the download queue.
 *
 * The queue lives here, above the router, so starting a 200-chapter series
 * download and then navigating away doesn't cancel it — it only stops when the
 * tab does.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSession } from "next-auth/react";
import type { OfflineChapter } from "@/lib/offline/db";
import {
  downloadChapter,
  isOfflineSupported,
  listDownloads,
  removeAll,
  removeChapter,
  discardPartial,
  removeSeries,
  requestPersistence,
  type DownloadProgress,
} from "@/lib/offline/manager";
import { flushProgressQueue, rememberSignedIn } from "@/lib/offline/progress";

export interface QueueItem {
  chapterId: string;
  seriesId: string;
  seriesTitle: string;
  number: number;
  coverPath?: string | null;
}

/** Why offline reading isn't available, when it isn't. */
export type OfflineBlocker = "insecure-origin" | "registration-failed" | null;

interface OfflineContextValue {
  /** False on http:// origins and when the service worker won't register. */
  supported: boolean;
  blocker: OfflineBlocker;
  online: boolean;
  /** Downloaded chapters, keyed by chapter id. */
  downloaded: Record<string, OfflineChapter>;
  queue: QueueItem[];
  active: { item: QueueItem; progress: DownloadProgress } | null;
  errors: Record<string, string>;
  enqueue: (items: QueueItem[]) => void;
  cancelAll: () => void;
  dequeue: (chapterId: string) => void;
  remove: (chapterId: string) => Promise<void>;
  removeSeriesDownloads: (seriesId: string) => Promise<void>;
  clearEverything: () => Promise<void>;
  refresh: () => Promise<void>;
}

const OfflineContext = createContext<OfflineContextValue | null>(null);

export function useOffline(): OfflineContextValue {
  const ctx = useContext(OfflineContext);
  if (!ctx) throw new Error("useOffline must be used inside <OfflineProvider>");
  return ctx;
}

export function OfflineProvider({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();
  const [supported, setSupported] = useState(false);
  const [blocker, setBlocker] = useState<OfflineBlocker>(null);
  const [online, setOnline] = useState(true);
  const [downloaded, setDownloaded] = useState<Record<string, OfflineChapter>>({});
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [active, setActive] = useState<OfflineContextValue["active"]>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Refs the worker loop reads, so it never restarts on a progress re-render.
  const queueRef = useRef<QueueItem[]>([]);
  const runningRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const activeIdRef = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    const all = await listDownloads();
    setDownloaded(Object.fromEntries(all.map((c) => [c.id, c])));
  }, []);

  // Register the service worker. Without it downloads still fill the cache but
  // nothing reads from it offline, so the whole feature is gated on this.
  useEffect(() => {
    setOnline(navigator.onLine);
    if (!isOfflineSupported()) {
      setBlocker("insecure-origin");
      return;
    }

    // Downloads are only useful once the worker is actually serving them, so
    // the UI stays hidden until registration succeeds.
    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then(() => {
        setSupported(true);
        setBlocker(null);
      })
      .catch(() => setBlocker("registration-failed"));
    void refresh();
  }, [refresh]);

  // Only trust a settled session: "unauthenticated" while offline just means
  // the session endpoint was unreachable, which must not clear the flag.
  useEffect(() => {
    if (status === "authenticated") rememberSignedIn(true);
    else if (status === "unauthenticated" && navigator.onLine) rememberSignedIn(false);
  }, [status, session]);

  useEffect(() => {
    const goOnline = () => {
      setOnline(true);
      void flushProgressQueue();
    };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    // Also flush on mount: the tab may have been closed while offline.
    void flushProgressQueue();
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  /** Drains the queue one chapter at a time until it's empty. */
  const pump = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;

    try {
      while (queueRef.current.length > 0) {
        const item = queueRef.current[0];
        const controller = new AbortController();
        abortRef.current = controller;
        activeIdRef.current = item.chapterId;
        setActive({ item, progress: { done: 0, total: 0 } });

        try {
          const record = await downloadChapter(item.chapterId, {
            signal: controller.signal,
            coverPath: item.coverPath,
            onProgress: (progress) => setActive({ item, progress }),
          });
          setDownloaded((prev) => ({ ...prev, [item.chapterId]: record }));
          setErrors((prev) => {
            if (!prev[item.chapterId]) return prev;
            const next = { ...prev };
            delete next[item.chapterId];
            return next;
          });
        } catch (err) {
          if ((err as Error).name === "AbortError") {
            // Cancelled: bin the half-written pages so they don't sit in
            // storage forever, then carry on with whatever is still queued
            // (cancelAll empties the queue, so that case exits here anyway).
            await discardPartial(item.chapterId).catch(() => {});
            queueRef.current = queueRef.current.filter((q) => q.chapterId !== item.chapterId);
            setQueue([...queueRef.current]);
            continue;
          }
          setErrors((prev) => ({
            ...prev,
            [item.chapterId]: (err as Error).message || "Download failed",
          }));
        }

        queueRef.current = queueRef.current.filter((q) => q.chapterId !== item.chapterId);
        setQueue([...queueRef.current]);
      }
    } finally {
      abortRef.current = null;
      activeIdRef.current = null;
      runningRef.current = false;
      setActive(null);
    }
  }, []);

  const enqueue = useCallback(
    (items: QueueItem[]) => {
      const known = new Set(queueRef.current.map((q) => q.chapterId));
      const fresh = items.filter((i) => !known.has(i.chapterId) && !downloaded[i.chapterId]);
      if (fresh.length === 0) return;

      queueRef.current = [...queueRef.current, ...fresh];
      setQueue([...queueRef.current]);
      // Ask for persistent storage on the first download rather than at boot,
      // so the permission prompt (where the browser shows one) has context.
      void requestPersistence();
      void pump();
    },
    [downloaded, pump]
  );

  const dequeue = useCallback((chapterId: string) => {
    queueRef.current = queueRef.current.filter((q) => q.chapterId !== chapterId);
    setQueue([...queueRef.current]);
    // Aborting only helps if this is the chapter actually in flight; a waiting
    // item is already gone now that it's out of the queue.
    if (activeIdRef.current === chapterId) abortRef.current?.abort();
  }, []);

  const cancelAll = useCallback(() => {
    queueRef.current = [];
    setQueue([]);
    abortRef.current?.abort();
  }, []);

  const remove = useCallback(
    async (chapterId: string) => {
      await removeChapter(chapterId);
      setDownloaded((prev) => {
        const next = { ...prev };
        delete next[chapterId];
        return next;
      });
    },
    []
  );

  const removeSeriesDownloads = useCallback(async (seriesId: string) => {
    await removeSeries(seriesId);
    await refresh();
  }, [refresh]);

  const clearEverything = useCallback(async () => {
    cancelAll();
    await removeAll();
    setDownloaded({});
  }, [cancelAll]);

  const value = useMemo<OfflineContextValue>(
    () => ({
      supported,
      blocker,
      online,
      downloaded,
      queue,
      active,
      errors,
      enqueue,
      cancelAll,
      dequeue,
      remove,
      removeSeriesDownloads,
      clearEverything,
      refresh,
    }),
    [
      supported,
      blocker,
      online,
      downloaded,
      queue,
      active,
      errors,
      enqueue,
      cancelAll,
      dequeue,
      remove,
      removeSeriesDownloads,
      clearEverything,
      refresh,
    ]
  );

  return <OfflineContext.Provider value={value}>{children}</OfflineContext.Provider>;
}
