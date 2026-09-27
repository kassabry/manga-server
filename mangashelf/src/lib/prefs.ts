"use client";

/**
 * One shared fetch of /api/user/preferences per page load.
 *
 * ThemeProvider and the dashboard both need preferences on mount, and each was
 * requesting them separately — two authenticated round trips for one row.
 */

const COLUMNS_KEY = "mangashelf:carouselColumns";

export interface Preferences {
  theme?: string;
  customColors?: string | null;
  carouselColumns?: number;
  [key: string]: unknown;
}

let inflight: Promise<Preferences | null> | null = null;

export function loadPreferences(): Promise<Preferences | null> {
  if (!inflight) {
    inflight = fetch("/api/user/preferences")
      .then((r) => (r.ok ? r.json() : null))
      .then((prefs: Preferences | null) => {
        if (prefs?.carouselColumns) cacheColumns(prefs.carouselColumns);
        return prefs;
      })
      .catch(() => null);
  }
  return inflight;
}

/** Forget the cached response after the user saves new preferences. */
export function invalidatePreferences() {
  inflight = null;
}

/**
 * Last known column count, readable during the first render.
 *
 * Rendering the grid at the default 6 and then reflowing to the saved 5 moves
 * every row, which lands a restored scroll offset in the wrong place — so the
 * real value has to be available before the first paint, not one fetch later.
 */
// 5 matches UserPreferences.carouselColumns' schema default, so a reader who has
// never touched the setting gets the right layout on the first paint too.
export function cachedColumns(fallback = 5): number {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(COLUMNS_KEY);
    const n = raw ? parseInt(raw, 10) : NaN;
    return Number.isFinite(n) && n > 0 ? n : fallback;
  } catch {
    return fallback;
  }
}

export function cacheColumns(columns: number) {
  try {
    window.localStorage.setItem(COLUMNS_KEY, String(columns));
  } catch {
    // Private mode / storage disabled — the fetched value still applies to this
    // page, it just won't be ready early on the next one.
  }
}
