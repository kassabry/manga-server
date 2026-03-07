"use client";

import { useEffect, useState, useMemo } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LIST_STATUS_LABELS, type ListStatus } from "@/lib/types";

interface ListEntryData {
  id: string;
  status: string;
  rating: number | null;
  updatedAt: string;
  series: {
    id: string;
    title: string;
    slug: string;
    type: string;
    coverPath: string | null;
    chapterCount: number;
    status: string | null;
  };
}

interface FollowEntry {
  seriesId: string;
  series: {
    id: string;
    title: string;
    slug: string;
    type: string;
    coverPath: string | null;
    chapterCount: number;
    status: string | null;
  };
}

interface ProgressInfo {
  seriesId: string;
  chaptersRead: number;
  totalChapters: number;
}

type SortOption = "title" | "recent" | "type";

export default function MyListPage() {
  const { data: session, status: authStatus } = useSession();
  const router = useRouter();
  const [entries, setEntries] = useState<ListEntryData[]>([]);
  const [follows, setFollows] = useState<FollowEntry[]>([]);
  const [progressMap, setProgressMap] = useState<Map<string, ProgressInfo>>(new Map());
  const [activeTab, setActiveTab] = useState<ListStatus | "all" | "following" | "in_progress">("all");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortOption>("recent");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authStatus === "unauthenticated") router.push("/login");
  }, [authStatus, router]);

  // Fetch list entries
  useEffect(() => {
    if (!session?.user) return;
    setLoading(true);

    const fetchEntries = async () => {
      // Fetch both manual list entries AND auto-populated reading entries
      const [listRes, readingRes] = await Promise.all([
        fetch("/api/user/list"),
        fetch("/api/user/list?status=reading"),
      ]);
      const listData = await listRes.json();
      const readingData = await readingRes.json();
      const manualEntries: ListEntryData[] = Array.isArray(listData) ? listData : [];
      const readingEntries: ListEntryData[] = Array.isArray(readingData) ? readingData : [];

      // Merge: start with manual entries, then add auto-populated reading entries not already present
      const seenIds = new Set(manualEntries.map((e) => e.series.id));
      const merged = [...manualEntries];
      for (const re of readingEntries) {
        if (!seenIds.has(re.series.id)) {
          seenIds.add(re.series.id);
          merged.push(re);
        }
      }
      setEntries(merged);

      // Fetch progress for each series in the merged list
      const progressPromises = merged.map(async (entry: ListEntryData) => {
        const pRes = await fetch(`/api/user/progress/${entry.series.id}`);
        const pData = await pRes.json();
        const completed = (pData.progress || []).filter(
          (p: { completed: boolean }) => p.completed
        ).length;
        return {
          seriesId: entry.series.id,
          chaptersRead: completed,
          totalChapters: entry.series.chapterCount,
        };
      });

      const progressResults = await Promise.all(progressPromises);
      const pMap = new Map<string, ProgressInfo>();
      for (const p of progressResults) pMap.set(p.seriesId, p);
      setProgressMap(pMap);
      setLoading(false);
    };

    fetchEntries();
  }, [session]);

  // Fetch followed series directly from Follow records (not from updates/chapters)
  useEffect(() => {
    if (!session?.user) return;
    fetch("/api/user/follows")
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setFollows(data);
        }
      });
  }, [session]);

  // Filter and sort
  const displayEntries = useMemo(() => {
    if (activeTab === "following") {
      let items = follows.map((f) => ({
        id: f.seriesId,
        status: "following" as string,
        rating: null,
        updatedAt: new Date().toISOString(),
        series: {
          ...f.series,
          chapterCount: f.series.chapterCount || 0,
        },
      }));

      if (search) {
        items = items.filter((e) =>
          e.series.title.toLowerCase().includes(search.toLowerCase())
        );
      }

      return items;
    }

    let filtered = entries;
    if (activeTab === "in_progress") {
      // Show reading entries that have some progress but aren't fully completed
      filtered = filtered.filter((e) => {
        if (e.status !== "reading") return false;
        const prog = progressMap.get(e.series.id);
        return prog && prog.chaptersRead > 0 && prog.chaptersRead < prog.totalChapters;
      });
    } else if (activeTab !== "all") {
      filtered = filtered.filter((e) => e.status === activeTab);
    }
    if (search) {
      filtered = filtered.filter((e) =>
        e.series.title.toLowerCase().includes(search.toLowerCase())
      );
    }

    const sorted = [...filtered];
    switch (sortBy) {
      case "title":
        sorted.sort((a, b) => a.series.title.localeCompare(b.series.title));
        break;
      case "recent":
        sorted.sort(
          (a, b) =>
            new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
        );
        break;
      case "type":
        sorted.sort((a, b) => a.series.type.localeCompare(b.series.type));
        break;
    }
    return sorted;
  }, [entries, follows, activeTab, search, sortBy, progressMap]);

  if (authStatus === "loading") return null;
  if (!session?.user) return null;

  const tabs: (ListStatus | "all" | "following" | "in_progress")[] = [
    "all",
    "following",
    "in_progress",
    "reading",
    "plan_to_read",
    "completed",
    "on_hold",
    "dropped",
  ];

  const tabLabels: Record<string, string> = {
    all: "All",
    following: "Following",
    in_progress: "In Progress",
    ...LIST_STATUS_LABELS,
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">My List</h1>
        <span className="text-sm text-text-secondary">
          {displayEntries.length} series
        </span>
      </div>

      {/* Search + Sort */}
      <div className="flex flex-wrap gap-3">
        <input
          type="text"
          placeholder="Filter by title..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 rounded-lg border border-border bg-bg-primary px-4 py-2 text-sm focus:border-accent focus:outline-none sm:max-w-xs"
        />
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortOption)}
          className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm focus:border-accent focus:outline-none"
        >
          <option value="recent">Recently Updated</option>
          <option value="title">Title A-Z</option>
          <option value="type">Type</option>
        </select>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 overflow-x-auto rounded-lg border border-border bg-bg-card p-1" style={{ scrollbarWidth: "none" }}>
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${
              activeTab === tab
                ? "bg-accent text-white"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {tabLabels[tab]}
          </button>
        ))}
      </div>

      {/* List */}
      {loading ? (
        <div className="py-12 text-center text-text-secondary">Loading...</div>
      ) : displayEntries.length === 0 ? (
        <div className="py-12 text-center text-text-secondary">
          {search
            ? "No series match your filter."
            : "No entries yet. Browse series to add them to your list."}
        </div>
      ) : (
        <div className="space-y-2">
          {displayEntries.map((entry) => {
            const prog = progressMap.get(entry.series.id);
            const progressPct =
              prog && prog.totalChapters > 0
                ? Math.round((prog.chaptersRead / prog.totalChapters) * 100)
                : 0;

            return (
              <Link
                key={entry.id}
                href={`/series/${entry.series.id}`}
                className="group block rounded-lg border border-border hover:border-accent"
              >
                <div className="flex items-center gap-4 p-3">
                  {entry.series.coverPath ? (
                    <img
                      src={entry.series.coverPath}
                      alt=""
                      className="h-16 w-11 rounded object-cover"
                    />
                  ) : (
                    <div className="h-16 w-11 rounded bg-bg-hover" />
                  )}
                  <div className="min-w-0 flex-1">
                    <h3 className="font-medium group-hover:text-accent">
                      {entry.series.title}
                    </h3>
                    <div className="mt-1 flex items-center gap-2 text-xs text-text-secondary">
                      <span>{entry.series.type}</span>
                      <span>&middot;</span>
                      <span>{entry.series.chapterCount} chapters</span>
                      {entry.series.status && (
                        <>
                          <span>&middot;</span>
                          <span>{entry.series.status}</span>
                        </>
                      )}
                    </div>
                    {/* Progress bar */}
                    {prog && prog.totalChapters > 0 && (
                      <div className="mt-2 flex items-center gap-2">
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-hover">
                          <div
                            className="h-full rounded-full bg-accent transition-all"
                            style={{ width: `${progressPct}%` }}
                          />
                        </div>
                        <span className="shrink-0 text-[10px] text-text-secondary">
                          {prog.chaptersRead}/{prog.totalChapters}
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="text-right">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        entry.status === "reading"
                          ? "bg-blue-900/50 text-blue-400"
                          : entry.status === "completed"
                          ? "bg-green-900/50 text-green-400"
                          : entry.status === "plan_to_read"
                          ? "bg-purple-900/50 text-purple-400"
                          : entry.status === "dropped"
                          ? "bg-red-900/50 text-red-400"
                          : entry.status === "following"
                          ? "bg-accent/20 text-accent"
                          : "bg-yellow-900/50 text-yellow-400"
                      }`}
                    >
                      {tabLabels[entry.status] || entry.status}
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
