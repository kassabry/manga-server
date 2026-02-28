"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";

interface ChapterUpdate {
  id: string;
  number: number;
  title: string | null;
  createdAt: string;
  readProgress: {
    completed: boolean;
    page: number;
  } | null;
}

interface SeriesGroup {
  series: {
    id: string;
    title: string;
    slug: string;
    coverPath: string | null;
    type: string;
  };
  latestDate: string;
  chapterCount: number;
  chapters: ChapterUpdate[];
}

export default function UpdatesPage() {
  const { data: session, status: authStatus } = useSession();
  const router = useRouter();
  const [seriesGroups, setSeriesGroups] = useState<SeriesGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedSeries, setExpandedSeries] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (authStatus === "unauthenticated") {
      router.push("/login");
    }
  }, [authStatus, router]);

  useEffect(() => {
    if (!session?.user) return;
    fetch("/api/user/updates?limit=100&grouped=true")
      .then((r) => r.json())
      .then((data) => {
        setSeriesGroups(data.seriesGroups || []);
        // Auto-expand series with 3 or fewer chapters
        const autoExpand = new Set<string>();
        for (const group of data.seriesGroups || []) {
          if (group.chapterCount <= 3) {
            autoExpand.add(group.series.id);
          }
        }
        setExpandedSeries(autoExpand);
        setLoading(false);
      });
  }, [session]);

  if (authStatus === "loading") return null;
  if (!session?.user) return null;

  function toggleExpand(seriesId: string) {
    setExpandedSeries((prev) => {
      const next = new Set(prev);
      if (next.has(seriesId)) {
        next.delete(seriesId);
      } else {
        next.add(seriesId);
      }
      return next;
    });
  }

  function expandAll() {
    setExpandedSeries(new Set(seriesGroups.map((g) => g.series.id)));
  }

  function collapseAll() {
    setExpandedSeries(new Set());
  }

  // Group seriesGroups by date for display
  const dateGroups: { date: string; groups: SeriesGroup[] }[] = [];
  const dateMap = new Map<string, SeriesGroup[]>();
  for (const group of seriesGroups) {
    const date = new Date(group.latestDate).toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
    if (!dateMap.has(date)) {
      dateMap.set(date, []);
      dateGroups.push({ date, groups: dateMap.get(date)! });
    }
    dateMap.get(date)!.push(group);
  }

  const totalChapters = seriesGroups.reduce(
    (acc, g) => acc + g.chapterCount,
    0
  );
  const unreadCount = seriesGroups.reduce(
    (acc, g) =>
      acc +
      g.chapters.filter((ch) => !ch.readProgress?.completed).length,
    0
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Updates</h1>
          <p className="text-sm text-text-secondary">
            New chapters from series you follow
            {totalChapters > 0 && (
              <> &mdash; {unreadCount} unread across {seriesGroups.length} series</>
            )}
          </p>
        </div>
        {seriesGroups.length > 0 && (
          <div className="flex gap-2">
            <button
              onClick={expandAll}
              className="rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-bg-hover"
            >
              Expand All
            </button>
            <button
              onClick={collapseAll}
              className="rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-bg-hover"
            >
              Collapse All
            </button>
          </div>
        )}
      </div>

      {loading ? (
        <div className="py-12 text-center text-text-secondary">Loading...</div>
      ) : seriesGroups.length === 0 ? (
        <div className="py-12 text-center text-text-secondary">
          No updates yet. Follow some series to see their new chapters here.
        </div>
      ) : (
        dateGroups.map(({ date, groups }) => (
          <section key={date}>
            <h2 className="mb-3 text-sm font-medium text-text-secondary">
              {date}
            </h2>
            <div className="space-y-2">
              {groups.map((group) => (
                <SeriesUpdateGroup
                  key={group.series.id}
                  group={group}
                  expanded={expandedSeries.has(group.series.id)}
                  onToggle={() => toggleExpand(group.series.id)}
                />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function SeriesUpdateGroup({
  group,
  expanded,
  onToggle,
}: {
  group: SeriesGroup;
  expanded: boolean;
  onToggle: () => void;
}) {
  const unreadChapters = group.chapters.filter(
    (ch) => !ch.readProgress?.completed
  );
  const allRead = unreadChapters.length === 0;
  const chapterRange =
    group.chapters.length > 1
      ? `Ch. ${group.chapters[group.chapters.length - 1].number}–${group.chapters[0].number}`
      : `Ch. ${group.chapters[0].number}`;

  return (
    <div
      className={`overflow-hidden rounded-xl border transition-colors ${
        allRead ? "border-border/50 opacity-60" : "border-border"
      }`}
    >
      {/* Series header — always visible, clickable to expand */}
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 bg-bg-secondary p-3 text-left hover:bg-bg-hover"
      >
        {group.series.coverPath ? (
          <img
            src={group.series.coverPath}
            alt=""
            className="h-14 w-10 rounded object-cover"
          />
        ) : (
          <div className="flex h-14 w-10 items-center justify-center rounded bg-bg-hover text-xs text-text-secondary">
            ?
          </div>
        )}
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold">{group.series.title}</h3>
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            <span className="rounded bg-bg-primary px-1.5 py-0.5">
              {group.series.type}
            </span>
            <span>{chapterRange}</span>
            <span>&middot;</span>
            <span>
              {group.chapterCount} chapter{group.chapterCount !== 1 ? "s" : ""}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {unreadChapters.length > 0 && (
            <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-accent px-1.5 text-[10px] font-bold text-white">
              {unreadChapters.length}
            </span>
          )}
          <svg
            className={`h-4 w-4 text-text-secondary transition-transform ${
              expanded ? "rotate-180" : ""
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </div>
      </button>

      {/* Expanded chapter list */}
      {expanded && (
        <div className="divide-y divide-border/50 border-t border-border">
          {group.chapters.map((chapter) => (
            <Link
              key={chapter.id}
              href={`/read/${chapter.id}${
                chapter.readProgress && !chapter.readProgress.completed
                  ? `?page=${chapter.readProgress.page}`
                  : ""
              }`}
              className={`flex items-center justify-between px-4 py-2.5 text-sm hover:bg-bg-hover ${
                chapter.readProgress?.completed ? "opacity-40" : ""
              }`}
            >
              <div className="flex items-center gap-3">
                <span className="font-medium">Ch. {chapter.number}</span>
                {chapter.title && (
                  <span className="text-text-secondary">{chapter.title}</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-secondary">
                  {formatRelativeDate(chapter.createdAt)}
                </span>
                {chapter.readProgress?.completed ? (
                  <svg
                    className="h-4 w-4 text-green-500"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                ) : (
                  <span className="rounded bg-accent/20 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                    NEW
                  </span>
                )}
              </div>
            </Link>
          ))}
          {/* Quick link to series page */}
          <Link
            href={`/series/${group.series.id}`}
            className="block px-4 py-2 text-center text-xs text-accent hover:bg-bg-hover"
          >
            View All Chapters &rarr;
          </Link>
        </div>
      )}
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
