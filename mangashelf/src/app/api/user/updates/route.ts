import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/db";

function toUTCDateStr(d: Date): string {
  return d.toISOString().slice(0, 10); // "YYYY-MM-DD"
}

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const limit = parseInt(request.nextUrl.searchParams.get("limit") || "50");
  const grouped = request.nextUrl.searchParams.get("grouped") === "true";

  const follows = await prisma.follow.findMany({
    where: { userId: session.user.id },
    select: { seriesId: true, createdAt: true },
  });

  if (follows.length === 0) {
    return NextResponse.json({ updates: [], seriesGroups: [] });
  }

  const followedAtMap = new Map(follows.map((f) => [f.seriesId, f.createdAt]));
  const seriesIds = follows.map((f) => f.seriesId);

  const earliestFollow = follows.reduce(
    (min, f) => (f.createdAt < min ? f.createdAt : min),
    follows[0].createdAt
  );
  const latestFollow = follows.reduce(
    (max, f) => (f.createdAt > max ? f.createdAt : max),
    follows[0].createdAt
  );

  // Build per-series sets of chapter numbers that already existed at follow time.
  // A number is "pre-existing" if ANY source had that chapter in the DB at or before
  // the user's follow date for that series. This prevents a newly-added source from
  // surfacing backlog chapters as "new" when those chapter numbers were already present.
  const preFollowRows = await prisma.chapter.findMany({
    where: {
      seriesId: { in: seriesIds },
      // Upper-bound by the latest follow date to avoid fetching the entire chapter history.
      // Per-series filtering against the correct followedAt is done in the loop below.
      createdAt: { lte: latestFollow },
    },
    select: { seriesId: true, number: true, createdAt: true },
  });

  const preFollowNums = new Map<string, Set<number>>();
  for (const row of preFollowRows) {
    const followedAt = followedAtMap.get(row.seriesId);
    if (!followedAt || new Date(row.createdAt) > followedAt) continue;
    if (!preFollowNums.has(row.seriesId)) preFollowNums.set(row.seriesId, new Set());
    preFollowNums.get(row.seriesId)!.add(row.number);
  }

  // Fetch all post-follow chapters for followed series, oldest first.
  // Ascending order ensures dedup by chapter number keeps the first-uploaded copy
  // (so if Asura uploads ch309 and Flame uploads the same ch309 a day later,
  // only the Asura copy is counted).
  // No small take limit — we filter down to the latest-date batch per series below.
  const chapters = await prisma.chapter.findMany({
    where: {
      seriesId: { in: seriesIds },
      createdAt: { gte: earliestFollow },
    },
    orderBy: { createdAt: "asc" },
    take: 20000, // safety cap only
    include: {
      series: {
        select: { id: true, title: true, slug: true, coverPath: true, type: true },
      },
    },
  });

  // Per-series: build a deduplicated chapter map and track the latest upload date
  // per source. Tracking per-source prevents one source's new batch from shadowing
  // another source's new chapters (e.g. ManhuaFast adding chapters today must not
  // hide a different source's chapter that was added yesterday).
  type ChapterRow = (typeof chapters)[0];
  type SeriesEntry = {
    series: ChapterRow["series"];
    byNumber: Map<number, ChapterRow>; // deduped: number -> first-uploaded chapter
    // latest date per source key so each source's batch is computed independently
    latestDateBySource: Map<string, { date: Date; dateStr: string }>;
  };

  const seriesMap = new Map<string, SeriesEntry>();

  for (const ch of chapters) {
    const followedAt = followedAtMap.get(ch.seriesId);
    // Skip chapters that existed before the user followed this series
    if (!followedAt || new Date(ch.createdAt) <= followedAt) continue;

    // Skip chapter numbers that already existed at follow time (from any source).
    // This stops a re-added or newly-added source from flooding "New from Followed"
    // with backlog chapters the user already knew about.
    if (preFollowNums.get(ch.seriesId)?.has(ch.number)) continue;

    const chDate = new Date(ch.createdAt);
    const chDateStr = toUTCDateStr(chDate);
    const srcKey = ch.source ?? "__none__";
    const entry = seriesMap.get(ch.seriesId);

    if (!entry) {
      seriesMap.set(ch.seriesId, {
        series: ch.series,
        byNumber: new Map([[ch.number, ch]]),
        latestDateBySource: new Map([[srcKey, { date: chDate, dateStr: chDateStr }]]),
      });
    } else {
      // Dedup by chapter number: ascending order guarantees first-seen = first-uploaded
      if (!entry.byNumber.has(ch.number)) {
        entry.byNumber.set(ch.number, ch);
      }
      const srcLatest = entry.latestDateBySource.get(srcKey);
      if (!srcLatest || chDate > srcLatest.date) {
        entry.latestDateBySource.set(srcKey, { date: chDate, dateStr: chDateStr });
      }
    }
  }

  // For each series: keep only chapters from each source's latest calendar-date batch.
  // If source A uploaded ch230 last week and ch231 today → show only ch231.
  // If source B uploaded backlog chapters today → those are kept only for source B's
  // batch, and source A's ch231 is still included based on source A's own latest date.
  // This prevents cross-source date contamination.
  const batchChapterIds: string[] = [];
  type BatchEntry = {
    series: ChapterRow["series"];
    batchChapters: ChapterRow[];
    latestDate: Date;
  };
  const batchData: BatchEntry[] = [];

  // When a series is re-imported (e.g. directory renamed, scanner wipes and recreates
  // chapters), all chapters get fresh createdAt timestamps that are > followedAt, and
  // preFollowNums is empty because the old records no longer exist. Every chapter then
  // passes the filters and floods the feed.  Cap each series' visible batch to the
  // MAX_BATCH_PER_SERIES highest-numbered chapters so a flood shows at most a handful
  // of entries rather than the entire back-catalogue, while single genuine releases
  // are completely unaffected.
  const MAX_BATCH_PER_SERIES = 5;

  for (const entry of seriesMap.values()) {
    // Each chapter is included only if its date matches its own source's latest date
    const dateBatch = Array.from(entry.byNumber.values()).filter((ch) => {
      const srcKey = ch.source ?? "__none__";
      const srcLatest = entry.latestDateBySource.get(srcKey);
      return srcLatest && toUTCDateStr(new Date(ch.createdAt)) === srcLatest.dateStr;
    });
    if (dateBatch.length === 0) continue;

    // Apply flood cap: keep only the highest-numbered chapters.
    // Sort descending by chapter number, take the first MAX_BATCH_PER_SERIES.
    const batchChapters = dateBatch.length > MAX_BATCH_PER_SERIES
      ? [...dateBatch].sort((a, b) => b.number - a.number).slice(0, MAX_BATCH_PER_SERIES)
      : dateBatch;

    // For display/sorting: use the latest date across all sources for this series
    const latestDate = Array.from(entry.latestDateBySource.values()).reduce(
      (max, src) => (src.date > max ? src.date : max),
      new Date(0)
    );
    batchChapterIds.push(...batchChapters.map((ch) => ch.id));
    batchData.push({ series: entry.series, batchChapters, latestDate });
  }

  // Fetch read progress for all batch chapters in one query
  const progressRecords = await prisma.readProgress.findMany({
    where: { userId: session.user.id, chapterId: { in: batchChapterIds } },
  });
  const progressMap = new Map(progressRecords.map((p) => [p.chapterId, p]));

  // Build series groups; exclude any series where every batch chapter is completed
  const seriesGroups = batchData
    .map(({ series, batchChapters, latestDate }) => {
      // Sort desc by chapter number for display (newest first in list)
      const sorted = [...batchChapters].sort((a, b) => b.number - a.number);
      const withProgress = sorted.map((ch) => {
        const prog = progressMap.get(ch.id);
        return {
          id: ch.id,
          number: ch.number,
          title: ch.title,
          createdAt: ch.createdAt.toISOString(),
          readProgress: prog ? { completed: prog.completed, page: prog.page } : null,
        };
      });

      // Drop series where every batch chapter has been completed
      if (withProgress.every((ch) => ch.readProgress?.completed)) return null;

      // Navigate to the oldest (lowest number) chapter in the batch
      const firstChapterId = withProgress[withProgress.length - 1].id;

      return {
        series,
        latestDate: latestDate.toISOString(),
        chapterCount: withProgress.length,
        chapters: withProgress,
        firstChapterId,
      };
    })
    .filter((g): g is NonNullable<typeof g> => g !== null)
    .sort((a, b) => new Date(b.latestDate).getTime() - new Date(a.latestDate).getTime())
    .slice(0, limit);

  if (grouped) {
    // Flat updates list for the home page carousel:
    // one entry per series — the newest chapter is the "headline", but the link
    // goes to the oldest chapter in the batch (so user starts reading in order).
    const updates = seriesGroups.map((g) => {
      const newestChapter = g.chapters[0]; // highest number (sorted desc)
      const oldestChapter = g.chapters[g.chapters.length - 1];
      return {
        id: newestChapter.id,
        number: newestChapter.number,
        title: newestChapter.title,
        createdAt: newestChapter.createdAt,
        series: g.series,
        readProgress: newestChapter.readProgress,
        totalNewChapters: g.chapterCount,
        minNewChapter: oldestChapter.number,
        firstChapterId: g.firstChapterId,
      };
    });

    return NextResponse.json({ updates, seriesGroups });
  }

  const updates = seriesGroups
    .flatMap((g) =>
      g.chapters.map((ch) => ({
        ...ch,
        series: g.series,
        totalNewChapters: g.chapterCount,
        minNewChapter: g.chapters[g.chapters.length - 1].number,
        firstChapterId: g.firstChapterId,
      }))
    )
    .slice(0, limit);

  return NextResponse.json({ updates, seriesGroups: [] });
}
