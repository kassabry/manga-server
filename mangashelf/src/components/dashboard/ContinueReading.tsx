"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { NavigationCarousel, CarouselItem } from "@/components/ui/NavigationCarousel";

interface ContinueItem {
  chapterId: string;
  chapterNumber: number;
  page: number;
  seriesId: string;
  seriesTitle: string;
  coverPath: string | null;
}

export function ContinueReading({ columns = 6 }: { columns?: number }) {
  const [items, setItems] = useState<ContinueItem[]>([]);

  useEffect(() => {
    fetch("/api/user/list?status=reading")
      .then((r) => r.json())
      .then(async (entries) => {
        if (!Array.isArray(entries) || entries.length === 0) return;

        const continueItems: ContinueItem[] = [];
        for (const entry of entries.slice(0, 20)) {
          const res = await fetch(`/api/user/progress/${entry.series.id}`);
          const data = await res.json();
          const latest = data.progress?.sort(
            (a: { readAt: string }, b: { readAt: string }) =>
              new Date(b.readAt).getTime() - new Date(a.readAt).getTime()
          )[0];

          if (latest && !latest.completed) {
            continueItems.push({
              chapterId: latest.chapterId,
              chapterNumber: latest.chapter.number,
              page: latest.page,
              seriesId: entry.series.id,
              seriesTitle: entry.series.title,
              coverPath: entry.series.coverPath,
            });
          }
        }
        setItems(continueItems);
      });
  }, []);

  async function resetProgress(seriesId: string) {
    await fetch(`/api/user/list?seriesId=${seriesId}`, { method: "DELETE" });
    setItems((prev) => prev.filter((item) => item.seriesId !== seriesId));
  }

  if (items.length === 0) return null;

  return (
    <section>
      <h2 className="mb-4 text-lg font-semibold">Continue Reading</h2>
      <NavigationCarousel columns={columns}>
        {items.map((item) => (
          <CarouselItem key={item.chapterId}>
            <div className="group relative">
              <Link
                href={`/read/${item.chapterId}?page=${item.page}`}
                className="block"
              >
                <div className="relative aspect-[2/3] overflow-hidden rounded-lg bg-bg-card">
                  {item.coverPath ? (
                    <img
                      src={item.coverPath}
                      alt={item.seriesTitle}
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
                  {/* Progress badge */}
                  <div className="absolute bottom-1.5 left-1.5 right-1.5">
                    <div className="rounded bg-bg-secondary/90 px-2 py-0.5 text-center text-[10px] backdrop-blur-sm">
                      Ch. {item.chapterNumber} &middot; Pg {item.page + 1}
                    </div>
                  </div>
                </div>
                <h3 className="mt-1.5 line-clamp-2 text-xs font-medium leading-tight group-hover:text-accent">
                  {item.seriesTitle}
                </h3>
              </Link>
              {/* Reset button - always visible (subtle) for touch devices, brighter on hover */}
              <button
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  resetProgress(item.seriesId);
                }}
                className="absolute right-1 top-1 z-10 rounded-full bg-black/60 p-1 text-white/50 transition hover:bg-red-500 hover:text-white"
                title="Remove from Continue Reading"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </CarouselItem>
        ))}
      </NavigationCarousel>
    </section>
  );
}
