"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";

interface Update {
  id: string;
  number: number;
  title: string | null;
  createdAt: string;
  series: {
    id: string;
    title: string;
    slug: string;
    coverPath: string | null;
    type: string;
  };
  readProgress: {
    completed: boolean;
  } | null;
  totalNewChapters: number;
  minNewChapter: number;
  firstChapterId: string;
}

export function UpdatesFeed() {
  const [updates, setUpdates] = useState<Update[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/user/updates?limit=20&grouped=true")
      .then((r) => r.json())
      .then((data) => {
        // Filter out series where the latest chapter has been read
        const unread = (data.updates || []).filter(
          (u: Update) => !u.readProgress?.completed
        );
        setUpdates(unread);
      });
  }, []);

  if (updates.length === 0) return null;

  function scroll(dir: "left" | "right") {
    if (!scrollRef.current) return;
    const amount = scrollRef.current.clientWidth * 0.8;
    scrollRef.current.scrollBy({
      left: dir === "left" ? -amount : amount,
      behavior: "smooth",
    });
  }

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">New from Followed</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => scroll("left")}
            className="rounded-lg border border-border p-1.5 hover:bg-bg-hover"
            aria-label="Scroll left"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <button
            onClick={() => scroll("right")}
            className="rounded-lg border border-border p-1.5 hover:bg-bg-hover"
            aria-label="Scroll right"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
          <Link
            href="/updates"
            className="ml-2 text-sm text-accent hover:text-accent-hover"
          >
            View All
          </Link>
        </div>
      </div>
      <div
        ref={scrollRef}
        className="-mx-4 flex gap-4 overflow-x-auto px-4 pb-2"
        style={{ scrollbarWidth: "none" }}
      >
        {updates.map((update) => (
          <Link
            key={update.id}
            href={`/read/${update.firstChapterId}`}
            className="group flex w-36 shrink-0 flex-col sm:w-40"
          >
            <div className="relative aspect-[2/3] overflow-hidden rounded-lg bg-bg-card">
              {update.series.coverPath ? (
                <img
                  src={update.series.coverPath}
                  alt={update.series.title}
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
              {/* Chapter badge */}
              <div className="absolute bottom-1.5 left-1.5 right-1.5">
                <div className="rounded bg-bg-secondary/90 px-2 py-1 text-center text-xs font-medium backdrop-blur-sm">
                  {update.totalNewChapters > 1
                    ? `Ch. ${update.minNewChapter}–${update.number}`
                    : `Ch. ${update.number}`}
                </div>
              </div>
              {/* New badge */}
              <div className="absolute right-1.5 top-1.5">
                <span className="rounded bg-accent px-1.5 py-0.5 text-[10px] font-bold text-white">
                  NEW
                </span>
              </div>
            </div>
            <h3 className="mt-1.5 line-clamp-2 text-xs font-medium leading-tight group-hover:text-accent">
              {update.series.title}
            </h3>
          </Link>
        ))}
      </div>
    </section>
  );
}
