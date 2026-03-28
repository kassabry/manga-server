"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { SeriesGrid } from "@/components/series/SeriesGrid";

interface SeriesData {
  id: string;
  title: string;
  coverPath: string | null;
  type: string;
  status: string | null;
  chapterCount: number;
  latestChapterNumber?: number | null;
}

interface FilterMeta {
  genres: { name: string; count: number }[];
  publishers: string[];
  statuses: string[];
  types: string[];
}

function BrowseContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [series, setSeries] = useState<SeriesData[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filterMeta, setFilterMeta] = useState<FilterMeta | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  const page = parseInt(searchParams.get("page") || "1");
  const search = searchParams.get("search") || "";
  const type = searchParams.get("type") || "";
  const genre = searchParams.get("genre") || "";
  const status = searchParams.get("status") || "";
  const publisher = searchParams.get("publisher") || "";
  const sort = searchParams.get("sort") || "title";

  // Fetch available filter options
  useEffect(() => {
    fetch("/api/genres")
      .then((r) => r.json())
      .then(setFilterMeta);
  }, []);

  const fetchSeries = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("limit", "24");
    if (search) params.set("search", search);
    if (type) params.set("type", type);
    if (genre) params.set("genre", genre);
    if (status) params.set("status", status);
    if (publisher) params.set("publisher", publisher);
    params.set("sort", sort);

    const res = await fetch(`/api/series?${params}`);
    const data = await res.json();
    setSeries(data.series || []);
    setTotal(data.total || 0);
    setLoading(false);
  }, [page, search, type, genre, status, publisher, sort]);

  useEffect(() => {
    fetchSeries();
  }, [fetchSeries]);

  function updateParam(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    params.delete("page");
    router.push(`/browse?${params}`);
  }

  function toggleGenre(g: string) {
    const current = genre.split(",").map((s) => s.trim()).filter(Boolean);
    const idx = current.indexOf(g);
    if (idx >= 0) {
      current.splice(idx, 1);
    } else {
      current.push(g);
    }
    updateParam("genre", current.join(","));
  }

  function clearAllFilters() {
    router.push("/browse");
  }

  const selectedGenres = genre.split(",").map((s) => s.trim()).filter(Boolean);
  const hasFilters = !!(search || type || genre || status || publisher);
  const totalPages = Math.ceil(total / 24);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">Browse</h1>
          <span className="text-sm text-text-secondary">{total} series</span>
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm ${
            showFilters || hasFilters
              ? "border-accent bg-accent/10 text-accent"
              : "border-border hover:bg-bg-hover"
          }`}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
          </svg>
          Filters
          {hasFilters && (
            <span className="ml-1 flex h-4 w-4 items-center justify-center rounded-full bg-accent text-[10px] text-white">
              {[search, type, genre, status, publisher].filter(Boolean).length}
            </span>
          )}
        </button>
      </div>

      {/* Quick filter bar (always visible) */}
      <div className="flex flex-wrap gap-2">
        <select
          value={type}
          onChange={(e) => updateParam("type", e.target.value)}
          className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm focus:border-accent focus:outline-none"
        >
          <option value="">All Types</option>
          {(filterMeta?.types || ["Manga", "Manhwa", "Manhua", "LightNovels"]).map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        <select
          value={status}
          onChange={(e) => updateParam("status", e.target.value)}
          className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm focus:border-accent focus:outline-none"
        >
          <option value="">All Status</option>
          {(filterMeta?.statuses || ["Ongoing", "Completed", "Hiatus"]).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <select
          value={publisher}
          onChange={(e) => updateParam("publisher", e.target.value)}
          className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm focus:border-accent focus:outline-none"
        >
          <option value="">All Sources</option>
          {(filterMeta?.publishers || []).map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>

        <select
          value={sort}
          onChange={(e) => updateParam("sort", e.target.value)}
          className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm focus:border-accent focus:outline-none"
        >
          <option value="title">Title A–Z</option>
          <option value="title_desc">Title Z–A</option>
          <option value="recent">Recently Updated</option>
          <option value="recent_asc">Oldest Updated</option>
          <option value="created">Newest Added</option>
          <option value="created_asc">Oldest Added</option>
          <option value="rating">Highest Rated</option>
          <option value="rating_asc">Lowest Rated</option>
          <option value="chapters">Most Chapters</option>
          <option value="chapters_asc">Fewest Chapters</option>
        </select>

        {hasFilters && (
          <button
            onClick={clearAllFilters}
            className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400 hover:bg-red-500/20"
          >
            Clear All
          </button>
        )}
      </div>

      {/* Active filter chips */}
      {hasFilters && (
        <div className="flex flex-wrap gap-2">
          {search && (
            <FilterChip label={`Search: "${search}"`} onRemove={() => updateParam("search", "")} />
          )}
          {type && (
            <FilterChip label={`Type: ${type}`} onRemove={() => updateParam("type", "")} />
          )}
          {selectedGenres.map((g) => (
            <FilterChip key={g} label={g} onRemove={() => toggleGenre(g)} />
          ))}
          {status && (
            <FilterChip label={`Status: ${status}`} onRemove={() => updateParam("status", "")} />
          )}
          {publisher && (
            <FilterChip label={`Source: ${publisher}`} onRemove={() => updateParam("publisher", "")} />
          )}
        </div>
      )}

      {/* Expanded genre filter panel */}
      {showFilters && filterMeta && filterMeta.genres.length > 0 && (
        <div className="rounded-xl border border-border bg-bg-card p-4">
          <h3 className="mb-3 text-sm font-semibold">Genres</h3>
          <div className="flex flex-wrap gap-2">
            {filterMeta.genres.map((g) => (
              <button
                key={g.name}
                onClick={() => toggleGenre(g.name)}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  selectedGenres.includes(g.name)
                    ? "border-accent bg-accent/20 text-accent"
                    : "border-border text-text-secondary hover:border-text-secondary hover:text-text-primary"
                }`}
              >
                {g.name}
                <span className="ml-1 opacity-50">{g.count}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Results */}
      {loading ? (
        <div className="py-12 text-center text-text-secondary">Loading...</div>
      ) : (
        <SeriesGrid series={series} />
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            disabled={page <= 1}
            onClick={() => {
              const params = new URLSearchParams(searchParams.toString());
              params.set("page", String(page - 1));
              router.push(`/browse?${params}`);
            }}
            className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-bg-hover disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-sm text-text-secondary">
            Page {page} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => {
              const params = new URLSearchParams(searchParams.toString());
              params.set("page", String(page + 1));
              router.push(`/browse?${params}`);
            }}
            className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-bg-hover disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent/10 px-3 py-1 text-xs text-accent">
      {label}
      <button onClick={onRemove} className="hover:text-white">&times;</button>
    </span>
  );
}

export default function BrowsePage() {
  return (
    <Suspense fallback={<div className="py-12 text-center text-text-secondary">Loading...</div>}>
      <BrowseContent />
    </Suspense>
  );
}
