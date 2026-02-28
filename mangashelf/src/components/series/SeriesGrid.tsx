"use client";

import { SeriesCard } from "./SeriesCard";

interface SeriesData {
  id: string;
  title: string;
  coverPath: string | null;
  type: string;
  status: string | null;
  chapterCount: number;
}

interface SeriesGridProps {
  series: SeriesData[];
  title?: string;
}

export function SeriesGrid({ series, title }: SeriesGridProps) {
  if (series.length === 0) {
    return (
      <div className="py-12 text-center text-text-secondary">
        No series found.
      </div>
    );
  }

  return (
    <section>
      {title && (
        <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      )}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
        {series.map((s) => (
          <SeriesCard key={s.id} {...s} />
        ))}
      </div>
    </section>
  );
}
