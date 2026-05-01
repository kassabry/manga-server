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

  // Per-series: build a deduplicated chapter map and track the latest upload date.
  type ChapterRow = (typeof chapters)[0];
  type SeriesEntry = {
    series: ChapterRow["series"];
    byNumber: Map<number, ChapterRow>; // deduped: number -> first-uploaded chapter
    latestDate: Date;
    latestDateStr: string;
  };

  const seriesMap = new Map<string, SeriesEntry>();

  for (const ch of chapters) {
    const followedAt = followedAtMap.get(ch.seriesId);
    // Skip chapters that existed before the user followed this series
    if (!followedAt || ch.createdAt <= followedAt) continue;

    const chDate = new Date(ch.createdAt);
    const chDateStr = toUTCDateStr(chDate);
    const entry = seriesMap.get(ch.seriesId);

    if (!entry) {
      seriesMap.set(ch.seriesId, {
        series: ch.series,
        byNumber: new Map([[ch.number, ch]]),
        latestDate: chDate,
        latestDateStr: chDateStr,
      });
    } else {
      // Dedup by chapter number: ascending order guarantees first-seen = first-uploaded
      if (!entry.byNumber.has(ch.number)) {
        entry.byNumber.set(ch.number, ch);
      }
      if (chDate > entry.latestDate) {
        entry.latestDate = chDate;
        entry.latestDateStr = chDateStr;
      }
    }
  }

  // For each series: keep only chapters from the latest calendar-date batch.
  // If ch230 came out last week and ch231 came out today, show only ch231.
  // If ch230 and ch231 both came out today, show both.
  const batchChapterIds: string[] = [];
  type BatchEntry = {
    series: ChapterRow["series"];
    batchChapters: ChapterRow[];
    latestDate: Date;
  };
  const batchData: BatchEntry[] = [];

  for (const entry of seriesMap.values()) {
    const batchChapters = Array.from(entry.byNumber.values()).filter(
      (ch) => toUTCDateStr(new Date(ch.createdAt)) === entry.latestDateStr
    );
    if (batchChapters.length === 0) continue;
    batchChapterIds.push(...batchChapters.map((ch) => ch.id));
    batchData.push({ series: entry.series, batchChapters, latestDate: entry.latestDate });
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
