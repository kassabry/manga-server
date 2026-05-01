"use client";

import { useEffect, useState, useCallback, useRef, use, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import Link from "next/link";

interface PageInfo {
  index: number;
  name: string;
  url: string;
}

interface ChapterData {
  id: string;
  number: number;
  title: string | null;
  pageCount: number;
  isEpub?: boolean;
  series: { id: string; title: string; slug: string };
  pages: PageInfo[];
  prevChapter: { id: string; number: number } | null;
  nextChapter: { id: string; number: number } | null;
  source: string | null;
  allChapters: { id: string; number: number; title: string | null; source: string | null }[];
}

type LayoutMode = "single" | "double" | "double-manga" | "longstrip";
type FitMode = "width" | "height" | "original";
type ReadingDirection = "ltr" | "rtl";
type BgColor = "black" | "dark" | "white";

interface ReaderSettings {
  layout: LayoutMode;
  fit: FitMode;
  direction: ReadingDirection;
  bgColor: BgColor;
  brightness: number;
  autoHideToolbar: boolean;
  swipeEnabled: boolean;
}

const DEFAULT_SETTINGS: ReaderSettings = {
  layout: "single",
  fit: "width",
  direction: "ltr",
  bgColor: "black",
  brightness: 100,
  autoHideToolbar: false,
  swipeEnabled: true,
};

function loadReaderSettings(): ReaderSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  const saved = localStorage.getItem("orvault-reader-settings");
  return saved ? { ...DEFAULT_SETTINGS, ...JSON.parse(saved) } : DEFAULT_SETTINGS;
}

function saveReaderSettings(settings: ReaderSettings) {
  localStorage.setItem("orvault-reader-settings", JSON.stringify(settings));
}

const BG_COLORS: Record<BgColor, string> = {
  black: "#000000",
  dark: "#1a1a2e",
  white: "#f5f5f5",
};

/**
 * Strip EPUB HTML to just the body content, removing scripts and
 * dangerous elements while keeping text formatting.
 */
function sanitizeEpubHtml(html: string): string {
  // Extract body content if full HTML document
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  const content = bodyMatch ? bodyMatch[1] : html;

  // Remove script and style tags
  return content
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/\s*on\w+="[^"]*"/gi, "") // Remove event handlers
    .replace(/\s*on\w+='[^']*'/gi, "");
}

// Returns the deduped chapter list for a given source, ordered by number asc.
function getFilteredChapters(
  allChapters: ChapterData["allChapters"],
  source: string | null
): ChapterData["allChapters"] {
  const src = source ?? allChapters[0]?.source ?? "Unknown";
  return allChapters
    .filter((c) => (c.source ?? "Unknown") === src)
    .reduce<ChapterData["allChapters"]>((acc, c) => {
      if (!acc.find((x) => x.number === c.number)) acc.push(c);
      return acc;
    }, []);
}

function getEffectivePrev(
  chapter: ChapterData,
  selectedSource: string | null
): { id: string; number: number } | null {
  const filtered = getFilteredChapters(chapter.allChapters, selectedSource);
  const idx = filtered.findIndex((c) => c.number === chapter.number);
  if (idx > 0) return filtered[idx - 1];
  if (idx === 0) return null;
  return chapter.prevChapter; // current chapter not in filtered list — fall back
}

function getEffectiveNext(
  chapter: ChapterData,
  selectedSource: string | null
): { id: string; number: number } | null {
  const filtered = getFilteredChapters(chapter.allChapters, selectedSource);
  const idx = filtered.findIndex((c) => c.number === chapter.number);
  if (idx >= 0 && idx < filtered.length - 1) return filtered[idx + 1];
  if (idx >= 0) return null;
  return chapter.nextChapter; // fall back
}

function ReaderContent({ chapterId }: { chapterId: string }) {
  const { data: session } = useSession();
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialPage = parseInt(searchParams.get("page") || "0");

  const [chapter, setChapter] = useState<ChapterData | null>(null);
  const [currentPage, setCurrentPage] = useState(initialPage);
  const [settings, setSettings] = useState<ReaderSettings>(DEFAULT_SETTINGS);
  const [showToolbar, setShowToolbar] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [showChapterPicker, setShowChapterPicker] = useState(false);
  const [autoHideTimer, setAutoHideTimer] = useState<ReturnType<typeof setTimeout> | null>(null);
  const [epubHtmlPages, setEpubHtmlPages] = useState<string[]>([]);
  // Reload: incrementing forces a fresh fetch of all images (cache-busts error-cached URLs)
  const [reloadKey, setReloadKey] = useState(0);
  const [isReloading, setIsReloading] = useState(false);
  const [showSourcePicker, setShowSourcePicker] = useState(false);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);

  // Touch/swipe state
  const touchStartX = useRef(0);
  const touchStartY = useRef(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Longstrip nav guard: prevent immediate chapter traversal on load
  const readyForNavRef = useRef(false);
  const hasScrolledRef = useRef(false);
  const scrollDistanceRef = useRef(0);

  // Track the visible page in longstrip mode for accurate progress saving
  const longstripPageRef = useRef(0);

  // Chapter picker: ref to the active chapter button for auto-scrolling
  const activeChapterBtnRef = useRef<HTMLButtonElement>(null);

  // Longstrip initial-scroll guard: only scroll to initialPage once per chapter load
  const scrolledToInitialRef = useRef(false);

  // Load settings from localStorage first, then override from server
  useEffect(() => {
    const local = loadReaderSettings();
    setSettings(local);

    if (session?.user) {
      fetch("/api/user/preferences")
        .then((r) => r.json())
        .then((prefs) => {
          if (!prefs || prefs.error) return;
          const serverSettings: Partial<ReaderSettings> = {};
          if (prefs.readerLayout) serverSettings.layout = prefs.readerLayout as LayoutMode;
          if (prefs.readerFit) serverSettings.fit = prefs.readerFit as FitMode;
          if (prefs.readerDirection) serverSettings.direction = prefs.readerDirection as ReadingDirection;
          if (prefs.readerBgColor) serverSettings.bgColor = prefs.readerBgColor as BgColor;
          if (prefs.readerBrightness !== undefined) serverSettings.brightness = prefs.readerBrightness;
          if (prefs.autoHideToolbar !== undefined) serverSettings.autoHideToolbar = prefs.autoHideToolbar;
          if (prefs.swipeEnabled !== undefined) serverSettings.swipeEnabled = prefs.swipeEnabled;
          const merged = { ...local, ...serverSettings };
          setSettings(merged);
          saveReaderSettings(merged);
        })
        .catch(() => {});
    }
  }, [session]);

  // Fetch chapter data
  useEffect(() => {
    // Reset nav guard and initial-scroll flag on chapter change
    readyForNavRef.current = false;
    hasScrolledRef.current = false;
    scrollDistanceRef.current = 0;
    scrolledToInitialRef.current = false;

    fetch(`/api/chapters/${chapterId}`)
      .then((r) => r.json())
      .then((data) => {
        setChapter(data);
        setSelectedSource((prev) => prev ?? data.source ?? null);
        const startPage = data.pages?.[0]?.name?.toLowerCase().includes("cover")
          ? Math.max(initialPage, 1)
          : initialPage;
        setCurrentPage(startPage);

        // Enable nav after delay + scroll
        setTimeout(() => {
          // Track scroll distance for next-chapter guard
          let lastScrollTop = 0;
          const scrollTracker = () => {
            const container = containerRef.current;
            if (container) {
              const delta = Math.abs(container.scrollTop - lastScrollTop);
              scrollDistanceRef.current += delta;
              lastScrollTop = container.scrollTop;
            }
            hasScrolledRef.current = true;
            readyForNavRef.current = true;
          };
          const container = containerRef.current;
          if (container) {
            container.addEventListener("scroll", scrollTracker, { passive: true });
            // Clean up on next chapter change via effect cleanup
            const cleanup = () => container.removeEventListener("scroll", scrollTracker);
            // Store cleanup for later (will be overwritten on next chapter)
            (window as unknown as Record<string, () => void>).__orvaultScrollCleanup = cleanup;
          }
          // Fallback: enable after 3 seconds regardless
          setTimeout(() => {
            readyForNavRef.current = true;
          }, 1000);
        }, 2000);
      });
  }, [chapterId, initialPage]);

  // Fetch EPUB HTML content when chapter is EPUB (re-runs when reloadKey increments)
  useEffect(() => {
    if (!chapter?.isEpub || chapter.pages.length === 0) {
      setEpubHtmlPages([]);
      return;
    }

    setEpubHtmlPages([]); // Show loading state while re-fetching
    // Load all EPUB chapter pages as HTML; reloadKey forces a fresh fetch on reload
    Promise.all(
      chapter.pages.map((page) =>
        fetch(pageUrl(page.url)).then((r) => r.text())
      )
    ).then(setEpubHtmlPages);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter?.id, chapter?.isEpub, chapter?.pages, reloadKey]);

  // Restore saved progress if no page param in URL
  useEffect(() => {
    if (!session?.user || !chapter || searchParams.get("page")) return;
    fetch(`/api/user/progress/${chapter.series.id}`)
      .then((r) => r.json())
      .then((data) => {
        const chapterProgress = (data.progress || []).find(
          (p: { chapterId: string }) => p.chapterId === chapter.id
        );
        if (chapterProgress && !chapterProgress.completed && chapterProgress.page > 0) {
          setCurrentPage(chapterProgress.page);
          if (settings.layout === "longstrip" && containerRef.current) {
            setTimeout(() => {
              const imgs = containerRef.current?.querySelectorAll("img");
              if (imgs && imgs[chapterProgress.page]) {
                imgs[chapterProgress.page].scrollIntoView({ behavior: "smooth" });
              }
            }, 500);
          }
        }
      })
      .catch(() => {});
  }, [session, chapter]);

  // Longstrip: when opening a chapter with ?page=X (e.g. from Continue Reading),
  // scroll the container to that image. setCurrentPage alone doesn't move the
  // scroll position because longstrip renders every page simultaneously.
  useEffect(() => {
    if (
      !chapter ||
      initialPage <= 0 ||
      settings.layout !== "longstrip" ||
      scrolledToInitialRef.current
    ) return;

    scrolledToInitialRef.current = true;
    let attempts = 0;

    const tryScroll = () => {
      const target = containerRef.current?.querySelector<HTMLElement>(
        `img[data-page-index="${initialPage}"]`
      );
      if (target) {
        target.scrollIntoView({ behavior: "instant" });
      } else if (attempts < 20) {
        attempts++;
        setTimeout(tryScroll, 150);
      }
    };
    // Short initial delay so images can start rendering
    setTimeout(tryScroll, 150);
  }, [chapter, initialPage, settings.layout]);

  // Chapter picker: scroll the active chapter into view when the panel opens
  useEffect(() => {
    if (!showChapterPicker || !activeChapterBtnRef.current) return;
    activeChapterBtnRef.current.scrollIntoView({ block: "center", behavior: "instant" });
  }, [showChapterPicker]);

  // Reload all chapter images (clears browser error-cache by appending ?r=N to every URL)
  const reloadChapter = useCallback(() => {
    setIsReloading(true);
    setReloadKey((k) => k + 1);
    setTimeout(() => setIsReloading(false), 1000);
  }, []);

  // Cache-bust helper: appends ?r=N when reloadKey > 0 so the browser re-fetches
  const pageUrl = useCallback(
    (url: string) => (reloadKey > 0 ? `${url}?r=${reloadKey}` : url),
    [reloadKey]
  );

  // Save settings when they change
  const updateSettings = useCallback((updates: Partial<ReaderSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...updates };
      saveReaderSettings(next);
      return next;
    });
  }, []);

  // Save reading progress
  const saveProgress = useCallback(
    async (page: number, completed: boolean) => {
      if (!session?.user || !chapter) return;
      fetch("/api/user/progress", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chapterId: chapter.id, page, completed }),
      });
    },
    [session, chapter]
  );

  useEffect(() => {
    if (!chapter) return;
    const timer = setTimeout(() => {
      const isLast = currentPage >= chapter.pages.length - 1;
      saveProgress(currentPage, isLast);
    }, 2000);
    return () => clearTimeout(timer);
  }, [currentPage, chapter, saveProgress]);

  // Save progress on page unload (tab close, browser back, etc.)
  useEffect(() => {
    if (!chapter || !session?.user) return;
    const handleUnload = () => {
      const page = settings.layout === "longstrip" ? longstripPageRef.current : currentPage;
      const isLast = page >= chapter.pages.length - 1;
      // Use sendBeacon for reliable delivery during unload
      navigator.sendBeacon(
        "/api/user/progress",
        new Blob(
          [JSON.stringify({ chapterId: chapter.id, page, completed: isLast })],
          { type: "application/json" }
        )
      );
    };
    window.addEventListener("beforeunload", handleUnload);
    return () => window.removeEventListener("beforeunload", handleUnload);
  }, [chapter, session, settings.layout, currentPage]);

  // Auto-hide toolbar
  useEffect(() => {
    if (!settings.autoHideToolbar || !showToolbar) return;
    if (autoHideTimer) clearTimeout(autoHideTimer);
    const timer = setTimeout(() => setShowToolbar(false), 3000);
    setAutoHideTimer(timer);
    return () => clearTimeout(timer);
  }, [showToolbar, settings.autoHideToolbar, currentPage]);

  // Longstrip: track which page is visible via IntersectionObserver
  useEffect(() => {
    if (!chapter || settings.layout !== "longstrip" || !containerRef.current) return;

    const container = containerRef.current;
    const images = container.querySelectorAll("img[data-page-index]");
    if (images.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Find the most visible image
        let maxRatio = 0;
        let visibleIndex = longstripPageRef.current;
        for (const entry of entries) {
          if (entry.isIntersecting && entry.intersectionRatio > maxRatio) {
            maxRatio = entry.intersectionRatio;
            const idx = parseInt((entry.target as HTMLElement).dataset.pageIndex || "0");
            visibleIndex = idx;
          }
        }
        if (maxRatio > 0) {
          longstripPageRef.current = visibleIndex;
          setCurrentPage(visibleIndex);
        }
      },
      { root: container, threshold: [0, 0.25, 0.5, 0.75] }
    );

    images.forEach((img) => observer.observe(img));
    return () => observer.disconnect();
  }, [chapter, settings.layout]);

  // Longstrip scroll-based chapter traversal (with nav guard)
  useEffect(() => {
    if (!chapter || settings.layout !== "longstrip" || !containerRef.current) return;

    const topSentinel = containerRef.current.querySelector("[data-sentinel='prev']");
    const bottomSentinel = containerRef.current.querySelector("[data-sentinel='next']");

    const observers: IntersectionObserver[] = [];

    const effPrev = getEffectivePrev(chapter, selectedSource);
    const effNext = getEffectiveNext(chapter, selectedSource);

    if (topSentinel && effPrev) {
      const prevId = effPrev.id;
      const obs = new IntersectionObserver(([entry]) => {
        if (entry.isIntersecting && readyForNavRef.current) {
          readyForNavRef.current = false;
          router.push(`/read/${prevId}`);
        }
      }, { threshold: 0.5 });
      obs.observe(topSentinel);
      observers.push(obs);
    }

    if (bottomSentinel) {
      const obs = new IntersectionObserver(([entry]) => {
        if (entry.isIntersecting && readyForNavRef.current && scrollDistanceRef.current > 500) {
          readyForNavRef.current = false;
          saveProgress(chapter.pages.length - 1, true);
          if (effNext) router.push(`/read/${effNext.id}`);
        }
      }, { threshold: 0.5 });
      obs.observe(bottomSentinel);
      observers.push(obs);
    }

    return () => observers.forEach(obs => obs.disconnect());
  }, [chapter, settings.layout, router, saveProgress, selectedSource]);

  // Page navigation helpers
  const totalPages = chapter?.pages.length || 0;

  const goToPage = useCallback(
    (page: number) => {
      if (!chapter) return;
      const clamped = Math.max(0, Math.min(page, chapter.pages.length - 1));
      setCurrentPage(clamped);
    },
    [chapter]
  );

  const goForward = useCallback(() => {
    if (!chapter) return;
    const step = settings.layout === "double" || settings.layout === "double-manga" ? 2 : 1;
    const nextPage = currentPage + step;
    if (nextPage >= chapter.pages.length) {
      saveProgress(currentPage, true);
      const next = getEffectiveNext(chapter, selectedSource);
      if (next) router.push(`/read/${next.id}`);
    } else {
      goToPage(nextPage);
    }
  }, [chapter, currentPage, settings.layout, goToPage, router, saveProgress, selectedSource]);

  const goBack = useCallback(() => {
    if (!chapter) return;
    const step = settings.layout === "double" || settings.layout === "double-manga" ? 2 : 1;
    const newPage = currentPage - step;
    if (newPage < 0) {
      const prev = getEffectivePrev(chapter, selectedSource);
      if (prev) router.push(`/read/${prev.id}`);
    } else {
      goToPage(currentPage - step);
    }
  }, [currentPage, settings.layout, goToPage, chapter, router, selectedSource]);

  const navigateForward = settings.direction === "rtl" ? goBack : goForward;
  const navigateBack = settings.direction === "rtl" ? goForward : goBack;

  // Keyboard navigation
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (settings.layout === "longstrip") {
        if (e.key === "Escape") setShowToolbar((s) => !s);
        return;
      }
      switch (e.key) {
        case "ArrowRight":
        case "d":
          navigateForward();
          break;
        case "ArrowLeft":
        case "a":
          navigateBack();
          break;
        case "f":
          updateSettings({
            fit: settings.fit === "width" ? "height" : settings.fit === "height" ? "original" : "width",
          });
          break;
        case "Escape":
          setShowToolbar((s) => !s);
          setShowSettings(false);
          setShowChapterPicker(false);
          setShowSourcePicker(false);
          break;
        case "m":
          setShowSettings((s) => !s);
          break;
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [navigateForward, navigateBack, settings.fit, settings.layout, updateSettings]);

  // Touch/swipe handling
  function handleTouchStart(e: React.TouchEvent) {
    if (!settings.swipeEnabled) return;
    touchStartX.current = e.touches[0].clientX;
    touchStartY.current = e.touches[0].clientY;
  }

  function handleTouchEnd(e: React.TouchEvent) {
    if (!settings.swipeEnabled || settings.layout === "longstrip") return;
    const deltaX = e.changedTouches[0].clientX - touchStartX.current;
    const deltaY = e.changedTouches[0].clientY - touchStartY.current;

    if (Math.abs(deltaX) > 50 && Math.abs(deltaX) > Math.abs(deltaY)) {
      if (deltaX > 0) {
        settings.direction === "rtl" ? goForward() : goBack();
      } else {
        settings.direction === "rtl" ? goBack() : goForward();
      }
    }
  }

  function handleTap(e: React.MouseEvent) {
    if (settings.layout === "longstrip") {
      setShowToolbar((s) => !s);
      return;
    }
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    if (x < 0.3) {
      navigateBack();
    } else if (x > 0.7) {
      navigateForward();
    } else {
      setShowToolbar((s) => !s);
      setShowSettings(false);
      setShowChapterPicker(false);
      setShowSourcePicker(false);
    }
  }

  if (!chapter) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-black">
        <div className="text-text-secondary">Loading...</div>
      </div>
    );
  }

  // Unique sources available for this series
  const uniqueSources = Array.from(
    new Set(chapter.allChapters.map((c) => c.source ?? "Unknown"))
  ).sort();

  // Active source: fall back to first available if selectedSource not present
  const activeSource =
    selectedSource && uniqueSources.includes(selectedSource)
      ? selectedSource
      : uniqueSources[0] ?? null;

  // Deduplicated chapters for active source (one entry per chapter number)
  const filteredChapters = getFilteredChapters(chapter.allChapters, activeSource);

  // Source-aware prev/next for all navigation in JSX
  const effectivePrev = getEffectivePrev(chapter, selectedSource);
  const effectiveNext = getEffectiveNext(chapter, selectedSource);

  const bgStyle = { backgroundColor: BG_COLORS[settings.bgColor] };
  const brightnessStyle = settings.brightness !== 100
    ? { filter: `brightness(${settings.brightness / 100})` }
    : {};

  const leftPage = chapter.pages[currentPage];
  const rightPage = settings.layout.startsWith("double")
    ? chapter.pages[currentPage + 1]
    : null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col" style={bgStyle}>
      {/* Top toolbar */}
      <div
        className={`z-40 flex items-center justify-between border-b border-white/10 bg-black/80 px-3 py-2 backdrop-blur transition-transform duration-200 ${
          showToolbar ? "translate-y-0" : "-translate-y-full"
        }`}
      >
        <div className="flex items-center gap-2 overflow-hidden">
          {/* Home button */}
          <Link href="/" className="shrink-0 text-sm text-white/70 hover:text-white" title="Home" onClick={(e) => {
            e.stopPropagation();
            const page = settings.layout === "longstrip" ? longstripPageRef.current : currentPage;
            saveProgress(page, page >= chapter.pages.length - 1);
          }}>
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" />
            </svg>
          </Link>

          {/* Prev chapter button */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (effectivePrev) {
                const page = settings.layout === "longstrip" ? longstripPageRef.current : currentPage;
                saveProgress(page, false);
                router.push(`/read/${effectivePrev.id}`);
              }
            }}
            disabled={!effectivePrev}
            className="shrink-0 rounded p-1 text-white/70 hover:text-white disabled:opacity-30"
            title={effectivePrev ? `Previous chapter (${effectivePrev.number})` : "No previous chapter"}
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>

          {/* Title — clicking navigates back to series page */}
          <Link
            href={`/series/${chapter.series.id}`}
            className="min-w-0 hover:opacity-80"
            title="Back to series"
            onClick={(e) => {
              e.stopPropagation();
              const page = settings.layout === "longstrip" ? longstripPageRef.current : currentPage;
              saveProgress(page, page >= chapter.pages.length - 1);
            }}
          >
            <div className="truncate text-sm font-medium text-white">
              {chapter.series.title}
            </div>
            <div className="text-xs text-white/50">
              Chapter {chapter.number}
              {chapter.title ? ` — ${chapter.title}` : ""}
            </div>
          </Link>

          {/* Next chapter button */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (effectiveNext) {
                const page = settings.layout === "longstrip" ? longstripPageRef.current : currentPage;
                saveProgress(page, true);
                router.push(`/read/${effectiveNext.id}`);
              }
            }}
            disabled={!effectiveNext}
            className="shrink-0 rounded p-1 text-white/70 hover:text-white disabled:opacity-30"
            title={effectiveNext ? `Next chapter (${effectiveNext.number})` : "No next chapter"}
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {/* Source picker button — only shown when multiple sources exist */}
          {uniqueSources.length > 1 && (
            <button
              onClick={() => { setShowSourcePicker(!showSourcePicker); setShowChapterPicker(false); setShowSettings(false); }}
              className={`rounded px-2 py-1 text-xs font-medium transition ${
                showSourcePicker
                  ? "bg-accent text-white"
                  : "bg-white/10 text-white/70 hover:bg-white/20 hover:text-white"
              }`}
              title="Select source site"
            >
              {activeSource ?? "Source"}
            </button>
          )}
          {/* Chapter picker button */}
          <button
            onClick={() => { setShowChapterPicker(!showChapterPicker); setShowSourcePicker(false); setShowSettings(false); }}
            className="rounded p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
            title="Jump to chapter"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          {settings.layout !== "longstrip" && (
            <span className="text-xs text-white/60">
              {currentPage + 1}/{totalPages}
            </span>
          )}
          {/* Reload button — clears browser error-cached images */}
          <button
            onClick={(e) => { e.stopPropagation(); reloadChapter(); }}
            className="rounded p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
            title="Reload images"
          >
            <svg
              className={`h-5 w-5 transition-transform ${isReloading ? "animate-spin" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <button
            onClick={() => { setShowSettings(!showSettings); setShowChapterPicker(false); setShowSourcePicker(false); }}
            className="rounded p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
            title="Reader settings (M)"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Source picker panel */}
      {showSourcePicker && uniqueSources.length > 1 && (
        <div className="absolute left-0 right-0 top-12 z-50 mx-auto max-w-xs">
          <div className="m-2 rounded-xl border border-white/10 bg-black/95 shadow-2xl backdrop-blur-xl">
            <div className="border-b border-white/10 px-4 py-2">
              <h3 className="text-sm font-semibold text-white">Source Site</h3>
            </div>
            <div className="p-2">
              {uniqueSources.map((src) => (
                <button
                  key={src}
                  onClick={() => {
                    setShowSourcePicker(false);
                    if (src === activeSource) return;
                    setSelectedSource(src);
                    // Navigate to the same chapter number in the new source
                    const sameChapter = chapter.allChapters.find(
                      (c) => (c.source ?? "Unknown") === src && c.number === chapter.number
                    );
                    if (sameChapter && sameChapter.id !== chapter.id) {
                      const page = settings.layout === "longstrip" ? longstripPageRef.current : currentPage;
                      saveProgress(page, page >= chapter.pages.length - 1);
                      router.push(`/read/${sameChapter.id}`);
                    }
                    // If no matching chapter in new source, selectedSource is updated
                    // so subsequent prev/next navigation uses the new source
                  }}
                  className={`w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                    src === activeSource
                      ? "bg-accent text-white"
                      : "text-white/70 hover:bg-white/10 hover:text-white"
                  }`}
                >
                  {src}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Chapter picker panel */}
      {showChapterPicker && (
        <div className="absolute left-0 right-0 top-12 z-50 mx-auto max-w-md">
          <div className="m-2 max-h-80 overflow-y-auto rounded-xl border border-white/10 bg-black/95 shadow-2xl backdrop-blur-xl">
            <div className="sticky top-0 border-b border-white/10 bg-black/95 px-4 py-2">
              <h3 className="text-sm font-semibold text-white">Chapters</h3>
            </div>
            <div className="p-2">
              {filteredChapters.map((ch) => (
                <button
                  key={ch.id}
                  ref={ch.number === chapter.number ? activeChapterBtnRef : undefined}
                  onClick={() => {
                    setShowChapterPicker(false);
                    if (ch.id !== chapter.id) {
                      const page = settings.layout === "longstrip" ? longstripPageRef.current : currentPage;
                      const isLast = page >= chapter.pages.length - 1;
                      saveProgress(page, isLast);
                      router.push(`/read/${ch.id}`);
                    }
                  }}
                  className={`w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                    ch.number === chapter.number
                      ? "bg-accent text-white"
                      : "text-white/70 hover:bg-white/10 hover:text-white"
                  }`}
                >
                  <span className="font-medium">Ch. {ch.number}</span>
                  {ch.title && <span className="ml-2 text-white/50">{ch.title}</span>}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Settings panel */}
      {showSettings && (
        <div className="absolute right-0 top-12 z-50 m-2 w-72 rounded-xl border border-white/10 bg-black/95 p-4 shadow-2xl backdrop-blur-xl sm:w-80">
          <h3 className="mb-3 text-sm font-semibold text-white">Reader Settings</h3>

          <div className="mb-4">
            <label className="mb-1.5 block text-xs text-white/50">Layout</label>
            <div className="grid grid-cols-2 gap-1.5">
              {(
                [
                  ["single", "Single Page"],
                  ["double", "Double Page"],
                  ["double-manga", "Double (Manga)"],
                  ["longstrip", "Long Strip"],
                ] as [LayoutMode, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => updateSettings({ layout: value })}
                  className={`rounded-lg px-2 py-1.5 text-xs ${
                    settings.layout === value
                      ? "bg-accent text-white"
                      : "bg-white/10 text-white/70 hover:bg-white/20"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {settings.layout !== "longstrip" && (
            <div className="mb-4">
              <label className="mb-1.5 block text-xs text-white/50">Scaling</label>
              <div className="grid grid-cols-3 gap-1.5">
                {(
                  [
                    ["width", "Width"],
                    ["height", "Height"],
                    ["original", "Original"],
                  ] as [FitMode, string][]
                ).map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => updateSettings({ fit: value })}
                    className={`rounded-lg px-2 py-1.5 text-xs ${
                      settings.fit === value
                        ? "bg-accent text-white"
                        : "bg-white/10 text-white/70 hover:bg-white/20"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {settings.layout !== "longstrip" && (
            <div className="mb-4">
              <label className="mb-1.5 block text-xs text-white/50">Direction</label>
              <div className="grid grid-cols-2 gap-1.5">
                <button
                  onClick={() => updateSettings({ direction: "ltr" })}
                  className={`rounded-lg px-2 py-1.5 text-xs ${
                    settings.direction === "ltr"
                      ? "bg-accent text-white"
                      : "bg-white/10 text-white/70 hover:bg-white/20"
                  }`}
                >
                  Left → Right
                </button>
                <button
                  onClick={() => updateSettings({ direction: "rtl" })}
                  className={`rounded-lg px-2 py-1.5 text-xs ${
                    settings.direction === "rtl"
                      ? "bg-accent text-white"
                      : "bg-white/10 text-white/70 hover:bg-white/20"
                  }`}
                >
                  Right → Left
                </button>
              </div>
            </div>
          )}

          <div className="mb-4">
            <label className="mb-1.5 block text-xs text-white/50">Background</label>
            <div className="grid grid-cols-3 gap-1.5">
              {(
                [
                  ["black", "Black"],
                  ["dark", "Dark"],
                  ["white", "White"],
                ] as [BgColor, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => updateSettings({ bgColor: value })}
                  className={`flex items-center justify-center gap-1 rounded-lg px-2 py-1.5 text-xs ${
                    settings.bgColor === value
                      ? "ring-2 ring-accent"
                      : ""
                  }`}
                  style={{ backgroundColor: BG_COLORS[value], color: value === "white" ? "#000" : "#fff" }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="mb-4">
            <label className="mb-1.5 flex items-center justify-between text-xs text-white/50">
              <span>Brightness</span>
              <span>{settings.brightness}%</span>
            </label>
            <input
              type="range"
              min={20}
              max={150}
              value={settings.brightness}
              onChange={(e) => updateSettings({ brightness: parseInt(e.target.value) })}
              className="w-full accent-accent"
            />
          </div>

          <div className="space-y-2">
            <label className="flex items-center justify-between text-xs">
              <span className="text-white/70">Swipe navigation</span>
              <button
                onClick={() => updateSettings({ swipeEnabled: !settings.swipeEnabled })}
                className={`h-5 w-9 rounded-full transition ${
                  settings.swipeEnabled ? "bg-accent" : "bg-white/20"
                }`}
              >
                <div
                  className={`h-4 w-4 rounded-full bg-white transition-transform ${
                    settings.swipeEnabled ? "translate-x-4" : "translate-x-0.5"
                  }`}
                />
              </button>
            </label>
            <label className="flex items-center justify-between text-xs">
              <span className="text-white/70">Auto-hide toolbar</span>
              <button
                onClick={() => updateSettings({ autoHideToolbar: !settings.autoHideToolbar })}
                className={`h-5 w-9 rounded-full transition ${
                  settings.autoHideToolbar ? "bg-accent" : "bg-white/20"
                }`}
              >
                <div
                  className={`h-4 w-4 rounded-full bg-white transition-transform ${
                    settings.autoHideToolbar ? "translate-x-4" : "translate-x-0.5"
                  }`}
                />
              </button>
            </label>
          </div>

          <div className="mt-4 border-t border-white/10 pt-3">
            <div className="text-[10px] text-white/30">
              <span className="font-mono">←→</span> Navigate &middot;{" "}
              <span className="font-mono">F</span> Fit &middot;{" "}
              <span className="font-mono">M</span> Menu &middot;{" "}
              <span className="font-mono">Esc</span> Toolbar
            </div>
          </div>
        </div>
      )}

      {/* Reader area */}
      <div
        ref={containerRef}
        className="relative flex-1 overflow-auto"
        style={brightnessStyle}
        onClick={handleTap}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {chapter.isEpub ? (
          /* EPUB text reader mode */
          <div className="mx-auto max-w-2xl px-4 py-8">
            {effectivePrev && (
              <div className="flex items-center justify-center py-6 text-white/40">
                <Link href={`/read/${effectivePrev.id}`} className="flex flex-col items-center gap-2 hover:text-white/60" onClick={(e) => e.stopPropagation()}>
                  <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                  </svg>
                  <span className="text-sm">Previous Volume ({effectivePrev.number})</span>
                </Link>
              </div>
            )}

            {epubHtmlPages.length > 0 ? (
              epubHtmlPages.map((html, i) => (
                <div
                  key={i}
                  data-page-index={i}
                  className="epub-content mb-8"
                  dangerouslySetInnerHTML={{ __html: sanitizeEpubHtml(html) }}
                />
              ))
            ) : (
              <div className="flex items-center justify-center py-20 text-white/40">
                <span>Loading content...</span>
              </div>
            )}

            <div className="flex items-center justify-center gap-4 py-12">
              {effectivePrev && (
                <Link
                  href={`/read/${effectivePrev.id}`}
                  className="rounded-lg bg-white/10 px-6 py-3 text-white hover:bg-white/20"
                  onClick={(e) => e.stopPropagation()}
                >
                  &larr; Previous
                </Link>
              )}
              {effectiveNext && (
                <Link
                  href={`/read/${effectiveNext.id}`}
                  className="rounded-lg bg-accent px-6 py-3 text-white hover:bg-accent/80"
                  onClick={(e) => e.stopPropagation()}
                >
                  Next &rarr;
                </Link>
              )}
            </div>
          </div>
        ) : settings.layout === "longstrip" ? (
          <div className="mx-auto max-w-3xl">
            {effectivePrev && (
              <div data-sentinel="prev" className="flex items-center justify-center py-8 text-white/40">
                <div className="flex flex-col items-center gap-2">
                  <svg className="h-6 w-6 animate-bounce" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                  </svg>
                  <span className="text-sm">Previous Chapter ({effectivePrev.number})</span>
                </div>
              </div>
            )}

            {chapter.pages.map((page) => (
              <img
                key={page.index}
                src={pageUrl(page.url)}
                alt={`Page ${page.index + 1}`}
                className="w-full"
                loading="lazy"
                draggable={false}
                data-page-index={page.index}
              />
            ))}

            <div className="flex items-center justify-center gap-4 py-12">
              {effectivePrev && (
                <Link
                  href={`/read/${effectivePrev.id}`}
                  className="rounded-lg bg-white/10 px-6 py-3 text-white hover:bg-white/20"
                  onClick={(e) => e.stopPropagation()}
                >
                  &larr; Previous
                </Link>
              )}
              {effectiveNext && (
                <Link
                  href={`/read/${effectiveNext.id}`}
                  className="rounded-lg bg-accent px-6 py-3 text-white hover:bg-accent/80"
                  onClick={(e) => e.stopPropagation()}
                >
                  Next &rarr;
                </Link>
              )}
            </div>

            {effectiveNext && (
              <div data-sentinel="next" className="flex items-center justify-center py-8 text-white/40">
                <div className="flex flex-col items-center gap-2">
                  <span className="text-sm">Loading next chapter...</span>
                  <svg className="h-6 w-6 animate-bounce" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </div>
            )}
          </div>
        ) : settings.layout.startsWith("double") ? (
          <div className="flex h-full items-center justify-center gap-0.5">
            {settings.layout === "double-manga" ? (
              <>
                {rightPage && (
                  <img
                    src={pageUrl(rightPage.url)}
                    alt={`Page ${currentPage + 2}`}
                    className={getFitClass(settings.fit, true)}
                    draggable={false}
                  />
                )}
                {leftPage && (
                  <img
                    src={pageUrl(leftPage.url)}
                    alt={`Page ${currentPage + 1}`}
                    className={getFitClass(settings.fit, true)}
                    draggable={false}
                  />
                )}
              </>
            ) : (
              <>
                {leftPage && (
                  <img
                    src={pageUrl(leftPage.url)}
                    alt={`Page ${currentPage + 1}`}
                    className={getFitClass(settings.fit, true)}
                    draggable={false}
                  />
                )}
                {rightPage && (
                  <img
                    src={pageUrl(rightPage.url)}
                    alt={`Page ${currentPage + 2}`}
                    className={getFitClass(settings.fit, true)}
                    draggable={false}
                  />
                )}
              </>
            )}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            {chapter.pages[currentPage] && (
              <img
                src={pageUrl(chapter.pages[currentPage].url)}
                alt={`Page ${currentPage + 1}`}
                className={getFitClass(settings.fit, false)}
                draggable={false}
              />
            )}
          </div>
        )}
      </div>

      {/* Bottom bar */}
      {settings.layout !== "longstrip" && (
        <div
          className={`z-40 border-t border-white/10 bg-black/80 px-3 py-2 backdrop-blur transition-transform duration-200 ${
            showToolbar ? "translate-y-0" : "translate-y-full"
          }`}
        >
          <div className="flex items-center gap-3">
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (effectivePrev) router.push(`/read/${effectivePrev.id}`);
              }}
              disabled={!effectivePrev}
              className="rounded p-1 text-white/60 hover:text-white disabled:opacity-30"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
              </svg>
            </button>

            <input
              type="range"
              min={0}
              max={totalPages - 1}
              value={currentPage}
              onChange={(e) => {
                e.stopPropagation();
                setCurrentPage(parseInt(e.target.value));
              }}
              onClick={(e) => e.stopPropagation()}
              className="flex-1 accent-accent"
              style={settings.direction === "rtl" ? { direction: "rtl" } : {}}
            />

            <button
              onClick={(e) => {
                e.stopPropagation();
                if (effectiveNext) router.push(`/read/${effectiveNext.id}`);
              }}
              disabled={!effectiveNext}
              className="rounded p-1 text-white/60 hover:text-white disabled:opacity-30"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        </div>
      )}

      {settings.layout !== "longstrip" && (
        <div className="hidden">
          {[1, 2, 3].map((offset) => {
            const nextPage = chapter.pages[currentPage + offset];
            return nextPage ? (
              <img key={offset} src={nextPage.url} alt="" />
            ) : null;
          })}
        </div>
      )}
    </div>
  );
}

function getFitClass(fit: FitMode, isDouble: boolean): string {
  const maxW = isDouble ? "max-w-[50vw]" : "max-w-full";
  switch (fit) {
    case "width":
      return `${maxW} max-h-screen object-contain`;
    case "height":
      return "max-h-screen object-contain";
    case "original":
      return "";
  }
}

export default function ReadPage({
  params,
}: {
  params: Promise<{ chapterId: string }>;
}) {
  const { chapterId } = use(params);
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-black text-white/50">
          Loading...
        </div>
      }
    >
      <ReaderContent chapterId={chapterId} />
    </Suspense>
  );
}
