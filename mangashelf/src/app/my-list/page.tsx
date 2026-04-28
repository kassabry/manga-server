"use client";

import { useEffect, useState, useMemo } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LIST_STATUS_LABELS, type ListStatus } from "@/lib/types";

interface CustomListSummary {
  id: string;
  name: string;
  entryCount: number;
  updatedAt: string;
}

interface CustomListDetail {
  id: string;
  name: string;
  entries: {
    id: string;
    seriesId: string;
    addedAt: string;
    series: {
      id: string;
      title: string;
      slug: string;
      type: string;
      coverPath: string | null;
      chapterCount: number;
      status: string | null;
    };
  }[];
}

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
  const [activeTab, setActiveTab] = useState<ListStatus | "all" | "following" | "in_progress" | "custom_lists">("all");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortOption>("recent");
  const [loading, setLoading] = useState(true);
  const [customLists, setCustomLists] = useState<CustomListSummary[]>([]);
  const [openListId, setOpenListId] = useState<string | null>(null);
  const [openListDetail, setOpenListDetail] = useState<CustomListDetail | null>(null);
  const [newListName, setNewListName] = useState("");
  const [editingListId, setEditingListId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");

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

  // Fetch custom lists
  const refreshCustomLists = () => {
    fetch("/api/user/custom-lists")
      .then((r) => r.json())
      .then((data) => Array.isArray(data) && setCustomLists(data));
  };

  useEffect(() => {
    if (!session?.user) return;
    refreshCustomLists();
  }, [session]);

  // Open a specific custom list
  useEffect(() => {
    if (!openListId) { setOpenListDetail(null); return; }
    fetch(`/api/user/custom-lists/${openListId}`)
      .then((r) => r.json())
      .then(setOpenListDetail);
  }, [openListId]);

  async function createCustomList() {
    if (!newListName.trim()) return;
    await fetch("/api/user/custom-lists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newListName.trim() }),
    });
    setNewListName("");
    refreshCustomLists();
  }

  async function deleteCustomList(id: string) {
    if (!confirm("Delete this list?")) return;
    await fetch(`/api/user/custom-lists/${id}`, { method: "DELETE" });
    if (openListId === id) setOpenListId(null);
    refreshCustomLists();
  }

  async function renameCustomList(id: string) {
    if (!editingName.trim()) return;
    await fetch(`/api/user/custom-lists/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: editingName.trim() }),
    });
    setEditingListId(null);
    refreshCustomLists();
  }

  async function removeFromCustomList(listId: string, seriesId: string) {
    await fetch(`/api/user/custom-lists/${listId}/entries?seriesId=${seriesId}`, { method: "DELETE" });
    // Refresh detail
    const updated = await fetch(`/api/user/custom-lists/${listId}`).then((r) => r.json());
    setOpenListDetail(updated);
    refreshCustomLists();
  }

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

  const tabs: (ListStatus | "all" | "following" | "in_progress" | "custom_lists")[] = [
    "all",
    "following",
    "in_progress",
    "reading",
    "plan_to_read",
    "completed",
    "on_hold",
    "dropped",
    "custom_lists",
  ];

  const tabLabels: Record<string, string> = {
    all: "All",
    following: "Following",
    in_progress: "In Progress",
    custom_lists: "Custom Lists",
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
      {activeTab !== "custom_lists" && <div className="flex flex-wrap gap-3">
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
      </div>}

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

      {/* Custom Lists tab content */}
      {activeTab === "custom_lists" && (
        <div className="space-y-4">
          {/* Create new list */}
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="New list name..."
              value={newListName}
              onChange={(e) => setNewListName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && createCustomList()}
              className="flex-1 rounded-lg border border-border bg-bg-primary px-4 py-2 text-sm focus:border-accent focus:outline-none sm:max-w-xs"
            />
            <button
              onClick={createCustomList}
              disabled={!newListName.trim()}
              className="rounded-lg bg-accent px-4 py-2 text-sm text-white disabled:opacity-40"
            >
              Create List
            </button>
          </div>

          {openListId && openListDetail ? (
            /* Opened list — show its series */
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setOpenListId(null)}
                  className="rounded p-1 text-text-secondary hover:text-text-primary"
                >
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                {editingListId === openListId ? (
                  <div className="flex flex-1 gap-2">
                    <input
                      autoFocus
                      type="text"
                      value={editingName}
                      onChange={(e) => setEditingName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") renameCustomList(openListId);
                        if (e.key === "Escape") setEditingListId(null);
                      }}
                      className="flex-1 rounded-lg border border-accent bg-bg-primary px-3 py-1 text-base font-semibold focus:outline-none"
                    />
                    <button onClick={() => renameCustomList(openListId)} className="text-sm text-accent">Save</button>
                    <button onClick={() => setEditingListId(null)} className="text-sm text-text-secondary">Cancel</button>
                  </div>
                ) : (
                  <>
                    <h2 className="flex-1 text-lg font-semibold">{openListDetail.name}</h2>
                    <button
                      onClick={() => { setEditingListId(openListId); setEditingName(openListDetail.name); }}
                      className="text-xs text-text-secondary hover:text-text-primary"
                    >
                      Rename
                    </button>
                    <button
                      onClick={() => deleteCustomList(openListId)}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Delete
                    </button>
                  </>
                )}
              </div>

              {openListDetail.entries.length === 0 ? (
                <p className="py-8 text-center text-text-secondary">No series in this list yet.</p>
              ) : (
                <div className="space-y-2">
                  {openListDetail.entries.map((entry) => (
                    <div key={entry.id} className="flex items-center gap-4 rounded-lg border border-border p-3">
                      <Link href={`/series/${entry.series.id}`} className="flex flex-1 items-center gap-4 hover:opacity-80 min-w-0">
                        {entry.series.coverPath ? (
                          <img src={entry.series.coverPath} alt="" className="h-16 w-11 rounded object-cover shrink-0" />
                        ) : (
                          <div className="h-16 w-11 shrink-0 rounded bg-bg-hover" />
                        )}
                        <div className="min-w-0">
                          <h3 className="font-medium truncate">{entry.series.title}</h3>
                          <div className="mt-1 text-xs text-text-secondary">
                            {entry.series.type} &middot; {entry.series.chapterCount} chapters
                          </div>
                        </div>
                      </Link>
                      <button
                        onClick={() => removeFromCustomList(openListId, entry.seriesId)}
                        className="shrink-0 rounded p-1 text-text-secondary hover:text-red-400"
                        title="Remove from list"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            /* List grid */
            customLists.length === 0 ? (
              <p className="py-12 text-center text-text-secondary">No custom lists yet. Create one above.</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {customLists.map((list) => (
                  <button
                    key={list.id}
                    onClick={() => setOpenListId(list.id)}
                    className="group flex items-center justify-between rounded-xl border border-border bg-bg-card p-4 text-left hover:border-accent"
                  >
                    <div>
                      <h3 className="font-medium group-hover:text-accent">{list.name}</h3>
                      <p className="mt-1 text-sm text-text-secondary">{list.entryCount} series</p>
                    </div>
                    <svg className="h-5 w-5 text-text-secondary group-hover:text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                ))}
              </div>
            )
          )}
        </div>
      )}

      {/* Regular list content (hidden when custom_lists tab active) */}
      {activeTab !== "custom_lists" && loading ? (
        <div className="py-12 text-center text-text-secondary">Loading...</div>
      ) : activeTab !== "custom_lists" && displayEntries.length === 0 ? (
        <div className="py-12 text-center text-text-secondary">
          {search
            ? "No series match your filter."
            : "No entries yet. Browse series to add them to your list."}
        </div>
      ) : activeTab !== "custom_lists" ? (
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
      ) : null}
    </div>
  );
}
