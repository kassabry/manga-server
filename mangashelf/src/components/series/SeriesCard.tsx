"use client";

import Link from "next/link";

interface SeriesCardProps {
  id: string;
  title: string;
  coverPath: string | null;
  type: string;
  status: string | null;
  chapterCount: number;
}

export function SeriesCard({
  id,
  title,
  coverPath,
  type,
  status,
  chapterCount,
}: SeriesCardProps) {
  return (
    <Link href={`/series/${id}`} className="group block">
      <div className="relative aspect-[2/3] overflow-hidden rounded-lg bg-bg-card">
        {coverPath ? (
          <img
            src={coverPath}
            alt={title}
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-text-secondary">
            <svg className="h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
            </svg>
          </div>
        )}
        {/* Badges */}
        <div className="absolute left-1 top-1 flex flex-col gap-1">
          <span className="rounded bg-bg-secondary/90 px-1.5 py-0.5 text-[10px] font-medium">
            {type}
          </span>
          {status && (
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                status === "Completed"
                  ? "bg-green-600/90"
                  : status === "Ongoing"
                  ? "bg-blue-600/90"
                  : "bg-yellow-600/90"
              }`}
            >
              {status}
            </span>
          )}
        </div>
        {/* Chapter count badge */}
        <div className="absolute bottom-1 right-1">
          <span className="rounded bg-bg-secondary/90 px-1.5 py-0.5 text-[10px]">
            {chapterCount} ch
          </span>
        </div>
      </div>
      <h3 className="mt-2 line-clamp-2 text-sm font-medium leading-tight group-hover:text-accent">
        {title}
      </h3>
    </Link>
  );
}
