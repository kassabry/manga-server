"use client";

/**
 * State + scroll restoration for the infinite-scroll grids.
 *
 * The app scrolls inside <main>, not the document (body is overflow-hidden), so
 * neither the browser's native scroll restoration nor the App Router's own
 * restoration can help — both only ever touch the document scroller. And even if
 * they could, an offset of 4000px is meaningless after a remount that refetched
 * only page 1: the rows that offset pointed at no longer exist.
 *
 * So both halves are cached together here — the pages already fetched, and where
 * the reader was inside them. A module-level cache is deliberate: client-side
 * back navigation keeps the module alive, and it avoids serializing hundreds of
 * series into sessionStorage on every scroll tick.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** id of the <main> element in the root layout — the real scroll container. */
export const SCROLL_ROOT_ID = "app-scroll";

interface Snapshot<T> {
  items: T[];
  page: number;
  hasMore: boolean;
  scrollTop: number;
}

// Bounded so a long browse session across many filter combinations can't grow
// without limit; insertion order makes the oldest key the first one out.
const MAX_SNAPSHOTS = 8;
const snapshots = new Map<string, Snapshot<unknown>>();

function remember<T>(key: string, snap: Snapshot<T>) {
  snapshots.delete(key);
  snapshots.set(key, snap as Snapshot<unknown>);
  while (snapshots.size > MAX_SNAPSHOTS) {
    const oldest = snapshots.keys().next().value;
    if (oldest === undefined) break;
    snapshots.delete(oldest);
  }
}

function scrollRoot(): HTMLElement | null {
  return typeof document === "undefined"
    ? null
    : document.getElementById(SCROLL_ROOT_ID);
}

export interface RestorableList<T> {
  items: T[];
  setItems: React.Dispatch<React.SetStateAction<T[]>>;
  page: number;
  setPage: React.Dispatch<React.SetStateAction<number>>;
  hasMore: boolean;
  setHasMore: React.Dispatch<React.SetStateAction<boolean>>;
  /** True when the current key came back with cached rows — skip the fetch. */
  restored: boolean;
  /** Throw the current key's snapshot away and start it over. */
  reset: () => void;
}

export function useRestorableList<T>(key: string): RestorableList<T> {
  // Read during render, not in an effect, so restored rows are present in the
  // same commit the scroll offset is reapplied in.
  const first = snapshots.get(key) as Snapshot<T> | undefined;

  const [activeKey, setActiveKey] = useState(key);
  const [items, setItems] = useState<T[]>(first?.items ?? []);
  const [page, setPage] = useState(first?.page ?? 1);
  const [hasMore, setHasMore] = useState(first?.hasMore ?? true);

  const restoredRef = useRef(first !== undefined);
  const pendingScroll = useRef(first?.scrollTop ?? 0);

  // The key changes in place when browse filters change. Swap to that key's
  // snapshot during render rather than remounting the whole page around a
  // `key` prop — the filter controls would lose their own state with it.
  if (key !== activeKey) {
    const next = snapshots.get(key) as Snapshot<T> | undefined;
    setActiveKey(key);
    setItems(next?.items ?? []);
    setPage(next?.page ?? 1);
    setHasMore(next?.hasMore ?? true);
    restoredRef.current = next !== undefined;
    pendingScroll.current = next?.scrollTop ?? 0;
  }

  const keyRef = useRef(key);
  keyRef.current = key;

  // Keep the cached pages current. Scroll offset lives on the snapshot object
  // and is mutated in place, so scrolling never re-runs this.
  useEffect(() => {
    // An empty list is not a snapshot worth keeping: storing one would make the
    // next visit "restore" nothing and skip its initial fetch, leaving the page
    // permanently blank.
    if (items.length === 0) return;
    remember(key, {
      items,
      page,
      hasMore,
      scrollTop: snapshots.get(key)?.scrollTop ?? 0,
    });
  }, [key, items, page, hasMore]);

  // Record the offset as it changes rather than on unmount: by the time an
  // unmount effect runs the list is gone, <main> has collapsed to the shorter
  // page, and the browser has already clamped scrollTop to 0.
  //
  // Written synchronously, not batched into a requestAnimationFrame: rAF stops
  // firing in a hidden or backgrounded tab, so the throttled version kept
  // whatever offset it happened to have when the frames stopped and restored
  // the reader to the wrong place. Reading scrollTop inside a scroll handler is
  // cheap — the value is already current, so it forces no layout.
  useEffect(() => {
    const el = scrollRoot();
    if (!el) return;

    const onScroll = () => {
      const snap = snapshots.get(keyRef.current);
      if (snap) snap.scrollTop = el.scrollTop;
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Reapply before paint, so coming back doesn't flash the top of the list
  // first. Covers are lazy-loaded inside fixed-aspect boxes, so the grid is
  // already at full height here even with no image bytes fetched.
  //
  // Runs on every key switch too, which doubles as "scroll to top when the
  // filters change" — a fresh key carries offset 0.
  //
  // Applied at most once per key. This effect can run more than once for the
  // same key — React re-runs effects on mount in development — and the first
  // version consumed the offset by zeroing it, so the second run put the reader
  // back where they were and then immediately scrolled them to the top again.
  const appliedKey = useRef<string | null>(null);
  useLayoutEffect(() => {
    const el = scrollRoot();
    if (!el) return;
    if (appliedKey.current === activeKey) return;
    appliedKey.current = activeKey;

    const target = pendingScroll.current;
    el.scrollTop = target;
    if (target === 0) return;

    // The first assignment is usually clamped: the rows are all there, but the
    // carousels above are still empty and the page is shorter than it will be,
    // so the scroller has nowhere to go yet. Keep reapplying as the page grows,
    // out to a second and a half, which covers covers arriving over a slow LAN.
    //
    // Timers rather than requestAnimationFrame, for the same background-tab
    // reason as the recording above.
    let settled = false;
    const timers = [0, 50, 120, 250, 500, 900, 1500].map((delay) =>
      setTimeout(() => {
        if (settled) return;
        if (Math.abs(el.scrollTop - target) <= 2) return;
        el.scrollTop = target;
      }, delay)
    );

    // Never fight the reader: if they scroll, flick or key their way somewhere
    // in the middle of that window, whatever they did wins and we stop.
    const giveUp = () => {
      settled = true;
    };
    const events = ["wheel", "touchstart", "keydown"] as const;
    events.forEach((e) =>
      window.addEventListener(e, giveUp, { passive: true, once: true })
    );

    return () => {
      timers.forEach(clearTimeout);
      events.forEach((e) => window.removeEventListener(e, giveUp));
    };
  }, [activeKey]);

  const reset = useCallback(() => {
    snapshots.delete(keyRef.current);
    pendingScroll.current = 0;
    restoredRef.current = false;
    appliedKey.current = keyRef.current;
    setItems([]);
    setPage(1);
    setHasMore(true);
    const el = scrollRoot();
    if (el) el.scrollTop = 0;
  }, []);

  return {
    items,
    setItems,
    page,
    setPage,
    hasMore,
    setHasMore,
    restored: restoredRef.current,
    reset,
  };
}
