"use client";

import { useEffect, useState, useMemo, use } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { LIST_STATUS_LABELS, type ListStatus } from "@/lib/types";

interface Chapter {
  id: string;
  number: number;
  title: string | null;
  pageCount: number;
  createdAt: string;
  source: string | null;
  sourceUrl: string | null;
}

interface SeriesDetail {
  id: string;
  title: string;
  slug: string;
  description: string | null;
  author: string | null;
  artist: string | null;
  status: string | null;
  type: string;
  genres: string | null;
  rating: number | null;
  coverPath: string | null;
  publisher: string | null;
  ageRating: string | null;
  chapterCount: number;
  chapters: Chapter[];
}

interface ProgressMap {
  [chapterId: string]: { completed: boolean; page: number };
}

interface ChapterGroup {
  number: number;
  title: string | null;
  pageCount: number;
  createdAt: string;
  sources: Chapter[];
}

export default function SeriesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: session } = useSession();
  const [series, setSeries] = useState<SeriesDetail | null>(null);
  const [following, setFollowing] = useState(false);
  const [listStatus, setListStatus] = useState<ListStatus | "">("");
  const [progress, setProgress] = useState<ProgressMap>({});
  const [sortDesc, setSortDesc] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<string>("all");

  const uniqueSources = useMemo(() => {
    const sources = new Set<string>();
    (series?.chapters || []).forEach((ch: Chapter) => {
      if (ch.source) sources.add(ch.source);
    });
    return Array.from(sources);
  }, [series]);

  const isGrouped = sourceFilter === "all" && uniqueSources.length > 1;

  const groupedChapters: ChapterGroup[] = useMemo(() => {
    if (!isGrouped || !series) return [];
    const map = new Map<number, ChapterGroup>();
    for (const ch of series.chapters) {
      if (!map.has(ch.number)) {
        map.set(ch.number, { number: ch.number, title: ch.title, pageCount: ch.pageCount, createdAt: ch.createdAt, sources: [] });
      }
      map.get(ch.number)!.sources.push(ch);
    }
    const groups = Array.from(map.values());
    groups.sort((a, b) => a.number - b.number);
    return sortDesc ? [...groups].reverse() : groups;
  }, [isGrouped, series, sortDesc]);

  useEffect(() => {
    fetch(`/api/series/${id}`)
      .then((r) => r.json())
      .then(setSeries);
  }, [id]);

  useEffect(() => {
    if (!session?.user || !id) return;

    fetch(`/api/user/follow/${id}`)
      .then((r) => r.json())
      .then((d) => setFollowing(d.following));

    fetch(`/api/user/list/${id}`)
      .then((r) => r.json())
      .then((d) => setListStatus(d.entry?.status || ""));

    fetch(`/api/user/progress/${id}`)
      .then((r) => r.json())
      .then((d) => {
        const map: ProgressMap = {};
        for (const p of d.progress || []) {
          map[p.chapterId] = { completed: p.completed, page: p.page };
        }
        setProgress(map);
      });
  }, [session, id]);

  async function toggleFollow() {
    await fetch(`/api/user/follow/${id}`, { method: "POST" });
    setFollowing(!following);
  }

  async function updateListStatus(status: string) {
    if (!status) {
      await fetch(`/api/user/list/${id}`, { method: "DELETE" });
      setListStatus("");
    } else {
      await fetch("/api/user/list", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seriesId: id, status }),
      });
      setListStatus(status as ListStatus);
    }
  }

  if (!series) {
    return <div className="py-12 text-center text-text-secondary">Loading...</div>;
  }

  const genres = series.genres?.split(",").map((g) => g.trim()).filter(Boolean) || [];
  const filteredChapters = sourceFilter === "all"
    ? series.chapters
    : series.chapters.filter((ch: Chapter) => ch.source === sourceFilter);

  const chapters = isGrouped ? [] : (sortDesc ? [...filteredChapters].reverse() : filteredChapters);

  // When showing all sources, display the max chapter count from any single source
  const displayChapterCount = isGrouped
    ? Math.max(...uniqueSources.map((s) => series.chapters.filter((ch: Chapter) => ch.source === s).length))
    : filteredChapters.length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-6 sm:flex-row">
        {/* Cover */}
        <div className="w-48 shrink-0">
          {series.coverPath ? (
            <img
              src={series.coverPath}
              alt={series.title}
              className="w-full rounded-xl shadow-lg"
            />
          ) : (
            <div className="flex aspect-[2/3] items-center justify-center rounded-xl bg-bg-card text-text-secondary">
              No Cover
            </div>
          )}
        </div>

        {/* Info */}
        <div className="flex-1 space-y-4">
          <h1 className="text-2xl font-bold sm:text-3xl">{series.title}</h1>

          <div className="flex flex-wrap gap-2 text-sm text-text-secondary">
            <span className="rounded bg-bg-card px-2 py-1">{series.type}</span>
            {series.status && (
              <span
                className={`rounded px-2 py-1 ${
                  series.status === "Completed"
                    ? "bg-green-900/50 text-green-400"
                    : series.status === "Ongoing"
                    ? "bg-blue-900/50 text-blue-400"
                    : "bg-yellow-900/50 text-yellow-400"
                }`}
              >
                {series.status}
              </span>
            )}
            {series.rating && (
              <span className="rounded bg-bg-card px-2 py-1">
                ★ {series.rating.toFixed(1)}
              </span>
            )}
          </div>

          {(series.author || series.artist) && (
            <div className="text-sm text-text-secondary">
              {series.author && <span>Author: {series.author}</span>}
              {series.author && series.artist && <span> &middot; </span>}
              {series.artist && <span>Artist: {series.artist}</span>}
            </div>
          )}

          {genres.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {genres.map((g) => (
                <Link
                  key={g}
                  href={`/browse?genre=${encodeURIComponent(g)}`}
                  className="rounded-full border border-border px-2.5 py-0.5 text-xs hover:border-accent hover:text-accent"
                >
                  {g}
                </Link>
              ))}
            </div>
          )}

          {series.description && (
            <p className="text-sm leading-relaxed text-text-secondary">
              {series.description}
            </p>
          )}

          {/* Action buttons */}
          {session?.user && (
            <div className="flex flex-wrap gap-3">
              <button
                onClick={toggleFollow}
                className={`rounded-lg px-4 py-2 text-sm font-medium ${
                  following
                    ? "border border-accent text-accent"
                    : "bg-accent text-white hover:bg-accent-hover"
                }`}
              >
                {following ? "Following" : "Follow"}
              </button>

              <select
                value={listStatus}
                onChange={(e) => updateListStatus(e.target.value)}
                className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm focus:border-accent focus:outline-none"
              >
                <option value="">Add to List...</option>
                {Object.entries(LIST_STATUS_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </div>

      {/* Chapter list */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            Chapters ({displayChapterCount})
          </h2>
          <button
            onClick={() => setSortDesc(!sortDesc)}
            className="text-sm text-text-secondary hover:text-text-primary"
          >
            {sortDesc ? "Newest First" : "Oldest First"}
          </button>
        </div>

        {uniqueSources.length > 1 && (
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs text-text-secondary">Source:</span>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="rounded-lg border border-border bg-bg-card px-2 py-1 text-xs focus:border-accent focus:outline-none"
            >
              <option value="all">All Sources</option>
              {uniqueSources.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        )}

        <div className="space-y-1">
          {isGrouped
            ? groupedChapters.map((group) => {
                const anyCompleted = group.sources.some((ch) => progress[ch.id]?.completed);
                const defaultChapter = group.sources[0];
                const defaultProg = progress[defaultChapter.id];
                return (
                  <div
                    key={group.number}
                    className={`flex items-center justify-between rounded-lg border border-border px-4 py-3 ${
                      anyCompleted ? "opacity-60" : ""
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      {anyCompleted && (
                        <span className="text-green-500 shrink-0" title="Read">✓</span>
                      )}
                      <span className="font-medium shrink-0">Chapter {group.number}</span>
                      {group.title && (
                        <span className="text-text-secondary truncate">— {group.title}</span>
                      )}
                      <div className="flex items-center gap-1 flex-wrap">
                        {group.sources.map((ch) => {
                          const prog = progress[ch.id];
                          return (
                            <Link
                              key={ch.id}
                              href={`/read/${ch.id}${prog && !prog.completed ? `?page=${prog.page}` : ""}`}
                              className={`rounded px-2 py-0.5 text-[11px] font-medium border transition-colors hover:border-accent hover:text-accent ${
                                prog?.completed
                                  ? "border-green-700/40 bg-green-900/20 text-green-500"
                                  : "border-border bg-bg-hover text-text-secondary"
                              }`}
                            >
                              {ch.source ?? "Unknown"}
                            </Link>
                          );
                        })}
                      </div>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-text-secondary shrink-0">
                      <span>{group.pageCount} pages</span>
                      <span>{new Date(group.createdAt).toLocaleDateString()}</span>
                    </div>
                  </div>
                );
              })
            : chapters.map((chapter) => {
                const prog = progress[chapter.id];
                return (
                  <Link
                    key={chapter.id}
                    href={`/read/${chapter.id}${prog && !prog.completed ? `?page=${prog.page}` : ""}`}
                    className={`flex items-center justify-between rounded-lg border border-border px-4 py-3 hover:border-accent ${
                      prog?.completed ? "opacity-60" : ""
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      {prog?.completed && (
                        <span className="text-green-500" title="Read">✓</span>
                      )}
                      <span className="font-medium">Chapter {chapter.number}</span>
                      {chapter.title && (
                        <span className="text-text-secondary">— {chapter.title}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-4 text-xs text-text-secondary">
                      <span>{chapter.pageCount} pages</span>
                      <span>{new Date(chapter.createdAt).toLocaleDateString()}</span>
                    </div>
                  </Link>
                );
              })}
        </div>
      </section>
    </div>
  );
}
