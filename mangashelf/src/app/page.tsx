"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ContinueReading } from "@/components/dashboard/ContinueReading";
import { UpdatesFeed } from "@/components/dashboard/UpdatesFeed";

const PAGE_SIZE = 30;

interface SeriesData {
  id: string;
  title: string;
  coverPath: string | null;
  type: string;
  status: string | null;
  chapterCount: number;
  updatedAt?: string;
  lastChapterAt?: string;
  latestChapterNumber?: number | null;
}

export default function HomePage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [needsSetup, setNeedsSetup] = useState(false);
  const [columns, setColumns] = useState(6);

  // Infinite scroll state
  const [series, setSeries] = useState<SeriesData[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const initialLoadDone = useRef(false);

  // Initial setup + prefs fetch
  useEffect(() => {
    const fetchAll = async () => {
      const setupPromise = fetch("/api/setup").then((r) => r.json());
      const prefsPromise = session?.user
        ? fetch("/api/user/preferences").then((r) => r.json()).catch(() => null)
        : Promise.resolve(null);

      const [setupData, prefs] = await Promise.all([setupPromise, prefsPromise]);

      if (setupData.needsSetup) {
        setNeedsSetup(true);
        router.replace("/setup");
        return;
      }

      if (prefs?.carouselColumns) {
        setColumns(prefs.carouselColumns);
      }
    };

    fetchAll();
  }, [router, session]);

  // Fetch one page of recently-updated series
  const fetchPage = useCallback(async (pageNum: number) => {
    setLoadingMore(true);
    try {
      const res = await fetch(
        `/api/series?sort=recent&limit=${PAGE_SIZE}&page=${pageNum}&excludeType=LightNovels`
      );
      const data = await res.json();
      const incoming: SeriesData[] = data.series || [];
      setSeries((prev) =>
        pageNum === 1 ? incoming : [...prev, ...incoming]
      );
      setHasMore(incoming.length === PAGE_SIZE);
    } finally {
      setLoadingMore(false);
    }
  }, []);

  // Load first page once setup check is done
  useEffect(() => {
    if (needsSetup || status === "loading") return;
    if (initialLoadDone.current) return;
    initialLoadDone.current = true;
    fetchPage(1);
  }, [needsSetup, status, fetchPage]);

  // IntersectionObserver — triggers when sentinel scrolls into view
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore) {
          setPage((p) => {
            const next = p + 1;
            fetchPage(next);
            return next;
          });
        }
      },
      { rootMargin: "200px" }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, fetchPage]);

  if (needsSetup || status === "loading") return null;

  return (
    <div className="space-y-8">
      {session?.user && (
        <>
          <UpdatesFeed />
          <ContinueReading columns={columns} />
        </>
      )}

      <section>
        <h2 className="mb-4 text-lg font-semibold">Recently Updated</h2>

        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
        >
          {series.map((s) => (
            <Link key={s.id} href={`/series/${s.id}`} className="group block">
              <div className="relative aspect-[2/3] overflow-hidden rounded-lg bg-bg-card">
                {s.coverPath ? (
                  <img
                    src={s.coverPath}
                    alt={s.title}
                    className="h-full w-full object-cover transition-transform group-hover:scale-105"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-text-secondary">
                    <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                    </svg>
                  </div>
                )}
                <div className="absolute bottom-0 left-0 right-0">
                  <div className="bg-gradient-to-t from-black/80 to-transparent px-2 pb-1.5 pt-4">
                    <div className="flex items-center justify-between text-[10px] text-white/90">
                      <span>
                        {s.latestChapterNumber != null
                          ? `Ch. ${s.latestChapterNumber}`
                          : `${s.chapterCount} ch`}
                      </span>
                      {s.lastChapterAt && (
                        <span className="text-white/60">
                          {formatRelativeDate(s.lastChapterAt)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
              <h3 className="mt-1.5 line-clamp-2 text-xs font-medium leading-tight group-hover:text-accent">
                {s.title}
              </h3>
            </Link>
          ))}
        </div>

        {/* Sentinel — observed by IntersectionObserver to trigger next page */}
        <div ref={sentinelRef} className="mt-4 flex justify-center py-4">
          {loadingMore && (
            <svg className="h-6 w-6 animate-spin text-accent" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          )}
          {!hasMore && series.length > 0 && (
            <p className="text-xs text-text-secondary">All caught up</p>
          )}
        </div>
      </section>
    </div>
  );
}

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
